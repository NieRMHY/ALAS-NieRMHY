import os
import time
from collections import deque
from datetime import datetime
from PIL import Image
# 此文件定义了截图处理逻辑。
# 管理各种截图捕获方式，并包含后台编码线程用于将图像序列化并通过 Base64 供 WebUI 实时渲染预览。
import base64
import threading
import queue as _queue

import cv2
import numpy as np

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import get_color, image_size, limit_in, save_image
from module.device.method.adb import Adb
from module.device.method.ascreencap import AScreenCap
from module.device.method.droidcast import DroidCast
from module.device.method.ldopengl import LDOpenGL
from module.device.method.nemu_ipc import NemuIpc
from module.device.method.scrcpy import Scrcpy
from module.device.method.wsa import WSA
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger

class Screenshot(Adb, WSA, DroidCast, AScreenCap, Scrcpy, NemuIpc, LDOpenGL):
    
    def __init__(self, screenshot_queue=None, screenshot_enabled=None, *args, **kwargs):
        self._screenshot_enabled = screenshot_enabled
        super().__init__(*args, **kwargs)
        self.screenshot_queue = screenshot_queue
        self._latest_frames = deque(maxlen=2)  
        self._encoder_stop = False
        self._encode_lock = threading.Lock()
        self._encoder_thread = threading.Thread(target=self._encoder_worker, daemon=True, name='ScreenshotEncoder')
        self._encoder_thread.start()
        self._encoder_paused = False
        self._screenshot_drop_count = 0
        self._last_queue_warn_time = 0.0
        self._queue_full_since = 0.0
    _screen_size_checked = False
    _screen_black_checked = False
    _minicap_uninstalled = False
    _screenshot_interval = Timer(0.1)
    _last_save_time = {}
    image: np.ndarray

    @cached_property
    def screenshot_methods(self):
        return {
            'ADB': self.screenshot_adb,
            'ADB_nc': self.screenshot_adb_nc,
            'uiautomator2': self.screenshot_uiautomator2,
            'aScreenCap': self.screenshot_ascreencap,
            'aScreenCap_nc': self.screenshot_ascreencap_nc,
            'DroidCast': self.screenshot_droidcast,
            'DroidCast_raw': self.screenshot_droidcast_raw,
            'scrcpy': self.screenshot_scrcpy,
            'nemu_ipc': self.screenshot_nemu_ipc,
            'ldopengl': self.screenshot_ldopengl,
        }

    @cached_property
    def screenshot_method_override(self) -> str:
        return ''

    def screenshot(self):
        """
        Returns:
            np.ndarray:
        """
        self._screenshot_interval.wait()
        self._screenshot_interval.reset()

        for _ in range(2):
            if self.screenshot_method_override:
                method = self.screenshot_method_override
            else:
                method = self.config.Emulator_ScreenshotMethod
            method = self.screenshot_methods.get(method, self.screenshot_adb)

            if self.screenshot_queue is not None:
                try:
                    queue_size = self.screenshot_queue.qsize()
                except NotImplementedError:
                    # macOS 不支持 qsize()，此处跳过队列大小检查（或根据需求调整）
                    queue_size = 0  # 假设队列未满
                if queue_size >= 10:
                    logger.warning('截图队列已满，跳过本次抓图以避免编码开销')
                    continue

            self.image = method()

            if self.config.Emulator_ScreenshotDedithering:
                # This will take 40-60ms
                cv2.fastNlMeansDenoising(self.image, self.image, h=17, templateWindowSize=1, searchWindowSize=2)
            self.image = self._handle_orientated_image(self.image)

            if self.config.Error_SaveError:
                self.screenshot_deque.append({'time': datetime.now(), 'image': self.image})
            if self.screenshot_queue is not None and self.image is not None:
                try:
                    with self._encode_lock:
                        self._latest_frames.append(self.image.copy())
                except MemoryError:
                    logger.error('放入最新帧缓冲时 MemoryError，丢弃一帧并尝试回收内存')
                    import gc; gc.collect()
                except Exception as e:
                    logger.debug('放入最新帧缓冲失败: %s', e)

            if self.check_screen_size() and self.check_screen_black():
                break
            else:
                continue

        return self.image

    @property
    def has_cached_image(self):
        return hasattr(self, 'image') and self.image is not None

    def _handle_orientated_image(self, image):
        """
        Args:
            image (np.ndarray):

        Returns:
            np.ndarray:
        """
        width, height = image_size(self.image)
        if width == 1280 and height == 720:
            return image

        # Rotate screenshots only when they're not 1280x720
        if self.orientation == 0:
            pass
        elif self.orientation == 1:
            image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif self.orientation == 2:
            image = cv2.rotate(image, cv2.ROTATE_180)
        elif self.orientation == 3:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        else:
            raise ScriptError(f'Invalid device orientation: {self.orientation}')

        return image

    @cached_property
    def screenshot_deque(self):
        try:
            length = int(self.config.Error_ScreenshotLength)
        except ValueError:
            logger.error(f'Error_ScreenshotLength={self.config.Error_ScreenshotLength} is not an integer')
            raise RequestHumanTakeover
        # Limit in 1~400
        length = max(1, min(length, 400))
        return deque(maxlen=length)

    def save_screenshot(self, genre='items', interval=None, to_base_folder=False):
        """Save a screenshot. Use millisecond timestamp as file name.

        Args:
            genre (str, optional): Screenshot type.
            interval (int, float): Seconds between two save. Saves in the interval will be dropped.
            to_base_folder (bool): If save to base folder.

        Returns:
            bool: True if save succeed.
        """
        now = time.time()
        if interval is None:
            interval = self.config.SCREEN_SHOT_SAVE_INTERVAL

        if now - self._last_save_time.get(genre, 0) > interval:
            fmt = 'png'
            file = '%s.%s' % (int(now * 1000), fmt)

            folder = self.config.SCREEN_SHOT_SAVE_FOLDER_BASE if to_base_folder else self.config.SCREEN_SHOT_SAVE_FOLDER
            folder = os.path.join(folder, genre)
            if not os.path.exists(folder):
                os.mkdir(folder)

            file = os.path.join(folder, file)
            self.image_save(file)
            self._last_save_time[genre] = now
            return True
        else:
            self._last_save_time[genre] = now
            return False

    def screenshot_last_save_time_reset(self, genre):
        self._last_save_time[genre] = 0

    def screenshot_interval_set(self, interval=None):
        """
        Args:
            interval (int, float, str):
                Minimum interval between 2 screenshots in seconds.
                Or None for Optimization_ScreenshotInterval, 'combat' for Optimization_CombatScreenshotInterval
        """
        if interval is None:
            origin = self.config.Optimization_ScreenshotInterval
            interval = limit_in(origin, 0.1, 0.3)
            if interval != origin:
                logger.warning(f'Optimization.ScreenshotInterval {origin} is revised to {interval}')
                self.config.Optimization_ScreenshotInterval = interval
            # Allow nemu_ipc to have a lower default
            if self.config.Emulator_ScreenshotMethod in ['nemu_ipc', 'ldopengl']:
                interval = limit_in(origin, 0.1, 0.2)
        elif interval == 'combat':
            origin = self.config.Optimization_CombatScreenshotInterval
            interval = limit_in(origin, 0.3, 1.0)
            if interval != origin:
                logger.warning(f'Optimization.CombatScreenshotInterval {origin} is revised to {interval}')
                self.config.Optimization_CombatScreenshotInterval = interval
        elif isinstance(interval, (int, float)):
            # No limitation for manual set in code
            pass
        else:
            logger.warning(f'Unknown screenshot interval: {interval}')
            raise ScriptError(f'Unknown screenshot interval: {interval}')
        # Screenshot interval in scrcpy is meaningless,
        # video stream is received continuously no matter you use it or not.
        if self.config.Emulator_ScreenshotMethod == 'scrcpy':
            interval = 0.1

        if interval != self._screenshot_interval.limit:
            logger.info(f'Screenshot interval set to {interval}s')
            self._screenshot_interval.limit = interval

    def image_show(self, image=None):
        if image is None:
            image = self.image
        Image.fromarray(image).show()

    def image_save(self, file=None):
        if file is None:
            file = f'{int(time.time() * 1000)}.png'
        save_image(self.image, file)

    def check_screen_size(self):
        """
        Screen size must be 1280x720.
        Take a screenshot before call.
        """
        if self._screen_size_checked:
            return True

        orientated = False
        for _ in range(2):
            # Check screen size
            width, height = image_size(self.image)
            logger.attr('Screen_size', f'{width}x{height}')
            if width == 1280 and height == 720:
                self._screen_size_checked = True
                return True
            elif not orientated and (width == 720 and height == 1280):
                logger.info('Received orientated screenshot, handling')
                self.get_orientation()
                self.image = self._handle_orientated_image(self.image)
                orientated = True
                width, height = image_size(self.image)
                if width == 720 and height == 1280:
                    logger.info('Unable to handle orientated screenshot, continue for now')
                    return True
                else:
                    continue
            elif self.config.Emulator_Serial == 'wsa-0':
                self.display_resize_wsa(0)
                return False
            elif hasattr(self, 'app_is_running') and not self.app_is_running():
                logger.warning('Received orientated screenshot, game not running')
                return True
            else:
                logger.critical(f'Resolution not supported: {width}x{height}')
                logger.critical('Please set emulator resolution to 1280x720')
                raise RequestHumanTakeover

    def check_screen_black(self):
        if self._screen_black_checked:
            return True
        # Check screen color
        # May get a pure black screenshot on some emulators.
        color = get_color(self.image, area=(0, 0, 1280, 720))
        if sum(color) < 1:
            if self.config.Emulator_Serial == 'wsa-0':
                for _ in range(2):
                    display = self.get_display_id()
                    if display == 0:
                        return True
                logger.info(f'Game running on display {display}')
                logger.warning('Game not running on display 0, will be restarted')
                self.app_stop_uiautomator2()
                return False
            elif self.config.Emulator_ScreenshotMethod == 'uiautomator2':
                logger.warning(f'Received pure black screenshots from emulator, color: {color}')
                logger.warning('Uninstall minicap and retry')
                self.uninstall_minicap()
                self._screen_black_checked = False
                return False
            else:
                logger.warning(f'Received pure black screenshots from emulator, color: {color}')
                logger.warning(f'Screenshot method `{self.config.Emulator_ScreenshotMethod}` '
                               f'may not work on emulator `{self.serial}`, or the emulator is not fully started')
                if self.is_mumu_family:
                    if self.config.Emulator_ScreenshotMethod == 'DroidCast':
                        self.droidcast_stop()
                    else:
                        logger.warning('If you are using MuMu X, please upgrade to version >= 12.1.5.0')
                self._screen_black_checked = False
                return False
        else:
            self._screen_black_checked = True
            return True

    def _encoder_worker(self):
        """后台编码线程：只编码最新帧并把 base64 放入 self.screenshot_queue
        支持暂停以在关闭调度器时停止编码并清空缓冲。"""
        while not getattr(self, '_encoder_stop', False):
            if getattr(self, '_encoder_paused', False):
                time.sleep(0.1)
                continue
            if getattr(self, '_screenshot_enabled', None) is not None:
                try:
                    if not bool(self._screenshot_enabled.value):
                        with self._encode_lock:
                            try:
                                self._latest_frames.clear()
                            except Exception:
                                pass
                        time.sleep(0.1)
                        continue
                except Exception:
                    pass
            try:
                if not self._latest_frames:
                    time.sleep(0.05)
                    continue

                try:
                    qmax = getattr(self.screenshot_queue, 'maxsize', 8) or 8
                    qsize = self.screenshot_queue.qsize() if self.screenshot_queue is not None else 0
                except Exception:
                    qmax, qsize = 8, 0

                nowt = time.time()
                q_threshold = max(1, int(qmax))

                if qsize >= q_threshold:
                    self._screenshot_drop_count += 1
                    if self._queue_full_since == 0.0:
                        self._queue_full_since = nowt
                    if nowt - self._last_queue_warn_time > 15.0:
                        logger.warning('雪风大人提示：已丢帧=%d qsize=%d max=%d', self._screenshot_drop_count, qsize, qmax)
                        self._last_queue_warn_time = nowt
                    if nowt - self._queue_full_since > 10.0:
                        time.sleep(0.3)
                        continue
                else:
                    if self._screenshot_drop_count:
                        self._screenshot_drop_count = 0
                    self._queue_full_since = 0.0

                with self._encode_lock:
                    try:
                        image = self._latest_frames.pop()
                    except Exception:
                        image = None
                    self._latest_frames.clear()

                if image is None:
                    continue

                rgb_image = image
                if rgb_image.ndim == 2:
                    rgb_image = cv2.cvtColor(rgb_image, cv2.COLOR_GRAY2BGR)
                elif rgb_image.shape[2] == 4:
                    try:
                        rgb_image = cv2.cvtColor(rgb_image, cv2.COLOR_RGBA2BGR)
                    except Exception:
                        rgb_image = rgb_image[..., :3][:, :, ::-1]
                elif rgb_image.shape[2] == 3:
                    try:
                        rgb_image = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)
                    except Exception:
                        rgb_image = rgb_image[:, :, ::-1]

                h, w = rgb_image.shape[:2]
                max_w, max_h = 900, 1600
                if w > max_w or h > max_h:
                    scale = min(max_w / w, max_h / h)
                    rgb_image = cv2.resize(rgb_image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

                quality = 100
                try:
                    qsize = self.screenshot_queue.qsize() if self.screenshot_queue is not None else 0
                    if qsize >= max(4, int(qmax * 0.75)):
                        quality = 80
                    elif qsize >= max(2, int(qmax * 0.5)):
                        quality = 90
                except Exception:
                    pass

                is_success, buffer = cv2.imencode(".jpg", rgb_image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                if not is_success:
                    continue
                img_base64 = base64.b64encode(buffer.tobytes()).decode("utf-8")

                if self.screenshot_queue is None:
                    continue

                try:
                    self.screenshot_queue.put(img_base64, timeout=0.1)
                except Exception:
                    try:
                        _ = self.screenshot_queue.get_nowait()
                        self.screenshot_queue.put_nowait(img_base64)
                        self._screenshot_drop_count += 1
                    except Exception:
                        self._screenshot_drop_count += 1

            except Exception as e:
                logger.debug('编码线程异常: %s', e)
                time.sleep(0.1)

    def pause_encoder(self):
        """暂停编码线程并清空 _latest_frames，适用于关闭调度器前调用。"""
        self._encoder_paused = True
        with self._encode_lock:
            try:
                self._latest_frames.clear()
            except Exception:
                pass

    def resume_encoder(self):
        """恢复编码线程（在清空队列后调用以避免瞬间显示旧帧）。"""
        self._encoder_paused = False

    def clear_screenshot_queue(self):
        """清空外部 screenshot_queue（若存在），用于恢复前清理旧数据。"""
        if self.screenshot_queue is None:
            return
        try:
            while True:
                self.screenshot_queue.get_nowait()
        except Exception:
            pass
