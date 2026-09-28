"""scrcpy 配置选项模块。

定义视频编码参数（帧率、比特率、H.264 Profile 等）和屏幕方向等运行时配置生成逻辑。
"""

import typing as t

import module.device.method.scrcpy.const as const


class ScrcpyOptions:
    """scrcpy 命令行与编码参数生成器。"""
    frame_rate = 6

    @classmethod
    def codec_options(cls, frame_rate: t.Optional[int] = None) -> str:
        """生成传递给 scrcpy 的自定义 MediaCodec 编码参数字符串。

        参考: https://developer.android.com/reference/android/media/MediaFormat

        Args:
            frame_rate: 采集帧率。默认使用类属性 frame_rate；调用方需要其他帧率时显式传入。

        Returns:
            str: 逗号分隔的键值对参数，形如 `key_profile=1,key_level=4096,...`。
        """
        frame_rate = cls.frame_rate if frame_rate is None else frame_rate
        options = dict(
            # H.264 profile 与 level
            # https://developer.android.com/reference/android/media/MediaCodecInfo.CodecProfileLevel
            # Baseline Profile，仅包含 I/P 帧
            key_profile=1,
            # Level 4.1，适用于 1280x720@30fps
            key_level=4096,
            # 最大质量
            key_quality=100,
            # https://developer.android.com/reference/android/media/MediaCodecInfo.EncoderCapabilities
            # 恒定质量模式
            key_bitrate_mode=0,
            # 0 表示所有帧均为关键帧
            key_i_frame_interval=0,
            # https://developer.android.com/reference/android/media/MediaCodecInfo.CodecCapabilities
            # COLOR_Format24bitBGR888
            key_color_format=12,
            # 采集帧率与输出帧率一致以降低 CPU 占用
            key_capture_rate=frame_rate,
            # 20Mbps，scrcpy 支持的最大输出码率
            key_bit_rate=20000000,
        )
        return ','.join([f'{k}={v}' for k, v in options.items()])

    @classmethod
    def arguments(cls) -> t.List[str]:
        """生成 scrcpy v1.25+ 格式的启动参数列表。

        Returns:
            list[str]: 格式为 `['log_level=info', 'max_size=1280', ...]` 的参数列表。
        """
        options = [
            'log_level=info',
            'max_size=1280',
            # 20Mbps，scrcpy 的最大输出比特率，若过高则回退到 8Mbps
            'bit_rate=20000000',
            # 单次截图耗时 <= 300ms 足以匹配人类操作反应速度
            f'max_fps={cls.frame_rate}',
            # 不锁定屏幕方向
            f'lock_video_orientation={const.LOCK_SCREEN_ORIENTATION_UNLOCKED}',
            # 固定启用隧道转发
            'tunnel_forward=true',
            # 固定启用控制
            'control=true',
            # 默认 Display 0
            'display_id=0',
            # 不显示触控轨迹点
            'show_touches=false',
            # 保持常亮为 false
            'stay_awake=false',
            # 编码器选项
            f'codec_options={cls.codec_options()}',
            'power_off_on_close=false',
            'clipboard_autosync=false',
            'downsize_on_error=false',
        ]
        return options

    @classmethod
    def command_v125(cls, jar_path='/data/local/tmp/scrcpy-server.jar') -> t.List[str]:
        """生成启动 scrcpy-server v1.25 的 shell 命令参数列表。

        Args:
            jar_path (str): 设备端的 server jar 路径。

        Returns:
            list[str]: 启动命令参数列表。
        """
        commands = [
            f'CLASSPATH={jar_path}',
            'app_process',
            '/',
            'com.genymobile.scrcpy.Server',
            '1.25',
        ]
        commands += cls.arguments()
        return commands

    @classmethod
    def command_v120(cls, jar_path='/data/local/tmp/scrcpy-server.jar',
                     frame_rate: t.Optional[int] = None) -> t.List[str]:
        """生成启动 scrcpy-server v1.20 的 shell 命令参数列表。

        Args:
            jar_path (str): 设备上的 scrcpy-server jar 路径。
            frame_rate (int | None): 采集与输出帧率。默认使用类属性 frame_rate。

        Returns:
            list[str]: 启动命令参数列表。
        """
        frame_rate = cls.frame_rate if frame_rate is None else frame_rate
        commands = [
            f"CLASSPATH={jar_path}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            "1.20",  # Scrcpy 服务端版本
            "info",  # 日志级别
            f"1280",  # 屏幕长边最大尺寸
            f"20000000",  # 视频比特率
            f"{frame_rate}",  # 最大帧率
            f"{const.LOCK_SCREEN_ORIENTATION_UNLOCKED}",  # 锁定屏幕方向
            "true",  # 隧道转发
            "-",  # 裁剪区域
            "false",  # 向客户端发送帧率
            "true",  # 启用控制
            "0",  # Display ID
            "false",  # 显示触摸点
            "false",  # 保持常亮
            cls.codec_options(frame_rate),  # 编码选项
            "-",  # 编码器名称
            "false",  # 服务端关闭后息屏
        ]
        return commands


if __name__ == '__main__':
    print(' '.join(ScrcpyOptions.command_v120()))
