import os
import queue
import threading
import numpy as np
import cv2
from PIL import Image

from module.exception import RequestHumanTakeover
from module.logger import logger
from module.config.config import AzurLaneConfig

def handle_ocr_error(e):
    logger.critical(f"Failed to load OCR dependencies: {e}")
    logger.critical(
        "无法加载 OCR 依赖，请安装微软 C++ 运行库 https://aka.ms/vs/17/release/vc_redist.x64.exe"
    )
    logger.critical("也有可能是 GPU 不支持加速引起，请尝试关闭 GPU 加速")
    logger.critical("如果上述方法都无法解决，请加群获取支持")
    raise RequestHumanTakeover


try:
    from rapidocr import RapidOCR, OCRVersion
    from rapidocr.ch_ppocr_rec import TextRecognizer
    from rapidocr.cal_rec_boxes import CalRecBoxes
    from rapidocr.utils.load_image import LoadImage
except Exception as e:
    handle_ocr_error(e)


config_name = os.environ.get("ALAS_CONFIG_NAME") or "alas"
config = AzurLaneConfig(config_name)


class _OcrJob:
    def __init__(self, func, args, kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.done = threading.Event()
        self.result = None
        self.exc_info = None

    def run(self):
        try:
            self.result = self.func(*self.args, **self.kwargs)
        except BaseException as e:
            self.exc_info = (e, e.__traceback__)
        finally:
            self.done.set()


_ocr_queue = queue.Queue()
_ocr_worker = None
_ocr_worker_lock = threading.Lock()
_ocr_worker_ident = None


def _ocr_worker_loop():
    global _ocr_worker_ident
    _ocr_worker_ident = threading.get_ident()
    while True:
        job = _ocr_queue.get()
        try:
            job.run()
        finally:
            _ocr_queue.task_done()


def _ensure_ocr_worker():
    global _ocr_worker
    with _ocr_worker_lock:
        if _ocr_worker is None or not _ocr_worker.is_alive():
            _ocr_worker = threading.Thread(
                target=_ocr_worker_loop,
                name='AlOcrQueue',
                daemon=True,
            )
            _ocr_worker.start()


def _run_ocr_queued(func, *args, **kwargs):
    if threading.get_ident() == _ocr_worker_ident:
        return func(*args, **kwargs)

    _ensure_ocr_worker()
    job = _OcrJob(func, args, kwargs)
    _ocr_queue.put(job)
    job.done.wait()

    if job.exc_info is not None:
        exc, traceback = job.exc_info
        raise exc.with_traceback(traceback)
    return job.result


class RecOnlyOCR(RapidOCR):
    """只加载识别模型，跳过 det 和 cls 的 ONNX 模型加载。"""

    def _initialize(self, cfg):
        self.text_score = cfg.Global.text_score
        self.min_height = cfg.Global.min_height
        self.width_height_ratio = cfg.Global.width_height_ratio

        self.use_det = False
        self.text_det = None

        self.use_cls = False
        self.text_cls = None

        self.use_rec = cfg.Global.use_rec
        cfg.Rec.engine_cfg = cfg.EngineConfig[cfg.Rec.engine_type.value]
        cfg.Rec.font_path = cfg.Global.font_path
        self.text_rec = TextRecognizer(cfg.Rec)

        self.load_img = LoadImage()
        self.max_side_len = cfg.Global.max_side_len
        self.min_side_len = cfg.Global.min_side_len

        self.cal_rec_boxes = CalRecBoxes()
        self.return_word_box = cfg.Global.return_word_box
        self.return_single_char_box = cfg.Global.return_single_char_box
        self.cfg = cfg


def _create_ocr(model_path, rec_keys_path, ocr_version):
    use_gpu = config.ocr_device == 'gpu'
    params = {
        "Global.use_det": False,
        "Global.use_cls": False,
        "Det.model_path": None,
        "Cls.model_path": None,
        "Rec.ocr_version": ocr_version,
        "Rec.model_path": model_path,
        "Rec.rec_keys_path": rec_keys_path,
        "EngineConfig.onnxruntime.use_dml": use_gpu,
    }
    return RecOnlyOCR(params=params)


# 懒加载：模块级不再创建模型，首次 init() 时才加载
_cn_model = None
_en_model = None
_jp_model = None
_tw_model = None


def _get_model(name):
    global _cn_model, _en_model, _jp_model, _tw_model
    if name in ("cn", "zhcn"):
        if _cn_model is None:
            _cn_model = _create_ocr(
                "bin/ocr_models/zh-CN/alocr-zh-cn-v3.dtk.onnx",
                "bin/ocr_models/zh-CN/cn.txt",
                OCRVersion.PPOCRV5,
            )
        return _cn_model
    elif name == "jp":
        if _jp_model is None:
            _jp_model = _create_ocr(
                "bin/ocr_models/JP/JP.onnx",
                "bin/ocr_models/JP/ppocrv5_dict.txt",
                OCRVersion.PPOCRV5,
            )
        return _jp_model
    elif name == "tw":
        if _tw_model is None:
            _tw_model = _create_ocr(
                "bin/ocr_models/TW/TW.onnx",
                "bin/ocr_models/TW/ppocrv5_dict.txt",
                OCRVersion.PPOCRV5,
            )
        return _tw_model
    else:
        if _en_model is None:
            _en_model = _create_ocr(
                "bin/ocr_models/en-US/alocr-en-us-v2.6.nvc.onnx",
                "bin/ocr_models/en-US/en.txt",
                OCRVersion.PPOCRV4,
            )
        return _en_model


def reset_ocr_model():
    def _reset():
        global _cn_model, _en_model, _jp_model, _tw_model
        logger.info("Resetting OCR models")
        _cn_model = None
        _en_model = None
        _jp_model = None
        _tw_model = None

    return _run_ocr_queued(_reset)


class AlOcr:
    def __init__(self, **kwargs):
        self.model = None
        self.name = kwargs.get("name", "en")
        self.params = {}
        self._model_loaded = False
        logger.info(
            f"Created AlOcr instance: name='{self.name}', kwargs={kwargs}, PID={os.getpid()}"
        )

    def init(self):
        self.model = _get_model(self.name)
        self._model_loaded = True

    def _ensure_loaded(self):
        if not self._model_loaded:
            self.init()

    def _save_debug_image(self, img, result):
        folder = "ocr_debug"
        if not os.path.exists(folder):
            os.makedirs(folder)

        # Get current time for filename uniqueness and sorting
        import time

        now = int(time.time() * 1000)
        # Clean result for filename
        res_clean = str(result).replace("\n", " ").replace("\r", " ").strip()
        # Remove invalid filename characters, keep some safe ones
        res_clean = "".join(
            [c for c in res_clean if c.isalnum() or c in (" ", "_", "-")]
        ).strip()
        if not res_clean:
            res_clean = "empty"

        filename = f"{self.name}_{res_clean}_{now}.png"
        filepath = os.path.join(folder, filename)

        try:
            if isinstance(img, np.ndarray):
                cv2.imwrite(filepath, img)
            elif isinstance(img, Image.Image):
                img.save(filepath)
            elif isinstance(img, str) and os.path.exists(img):
                import shutil

                shutil.copy(img, filepath)

            # Limit count to 100
            files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, f))
            ]
            if len(files) > 100:
                files.sort(key=os.path.getmtime)
                # Keep the last 100
                for f in files[:-100]:
                    try:
                        os.remove(f)
                    except:
                        pass
        except Exception as e:
            # We don't want to crash the main process due to debug saving failure
            logger.warning(f"Failed to save OCR debug image: {e}")

    def _ocr_direct(self, img_fp):
        logger.debug(f"[VERBOSE] AlOcr.ocr: Ensure loaded...")
        self._ensure_loaded()

        try:
            res = self.model(img_fp)
            txt = ""
            if hasattr(res, "txts") and res.txts:
                txt = res.txts[0]

            self._save_debug_image(img_fp, txt)
            return txt
        except Exception as e:
            logger.error(f"AlOcr.ocr exception: {e}")
            raise

    def ocr(self, img_fp):
        return _run_ocr_queued(self._ocr_direct, img_fp)

    def ocr_for_single_line(self, img_fp):
        return self.ocr(img_fp)

    def _ocr_for_single_lines_direct(self, img_list):
        self._ensure_loaded()
        results = []
        for i, img in enumerate(img_list):
            try:
                res = self.model(img)
                txt = ""
                if hasattr(res, "txts") and res.txts:
                    txt = res.txts[0]

                results.append(txt)
                self._save_debug_image(img, txt)
            except Exception as e:
                logger.error(f"AlOcr.ocr_for_single_lines exception on image {i}: {e}")
                raise
        return results

    def ocr_for_single_lines(self, img_list):
        return _run_ocr_queued(self._ocr_for_single_lines_direct, img_list)

    def set_cand_alphabet(self, cand_alphabet):
        pass

    def atomic_ocr(self, img_fp, cand_alphabet=None):
        res = self.ocr(img_fp)
        if cand_alphabet:
            res = "".join([c for c in res if c in cand_alphabet])
        return res

    def atomic_ocr_for_single_line(self, img_fp, cand_alphabet=None):
        res = self.ocr_for_single_line(img_fp)
        if cand_alphabet:
            res = "".join([c for c in res if c in cand_alphabet])
        return res

    def atomic_ocr_for_single_lines(self, img_list, cand_alphabet=None):
        results = self.ocr_for_single_lines(img_list)
        if cand_alphabet:
            results = [
                "".join([c for c in res if c in cand_alphabet]) for res in results
            ]
        return results
