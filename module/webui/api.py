import asyncio
import json
import os
import queue
import shutil
import subprocess
import threading
import time

import cv2
from starlette.responses import JSONResponse, HTMLResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect
from module.logger import logger

def api_cl1_stats(request):
    try:
        from module.statistics.opsi_month import get_opsi_stats
        instance_name = request.query_params.get("instance", "alas")
        stats = get_opsi_stats(instance_name=instance_name).get_detailed_summary()
        return JSONResponse({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"api_cl1_stats error: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

def api_ap_timeline(request):
    try:
        from module.statistics.opsi_month import get_ap_timeline
        instance_name = request.query_params.get("instance", "alas")
        timeline = get_ap_timeline(instance_name=instance_name)
        return JSONResponse({"success": True, "data": timeline})
    except Exception as e:
        logger.error(f"api_ap_timeline error: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

def serve_obs_overlay(request):
    """
    提供OBS专用覆盖层页面
    用户可以在浏览器中访问 http://IP:PORT/obs 或者在OBS中添加浏览器源
    """
    try:
        html_path = "module/webui/obs_overlay.html"
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content)
    except Exception as e:
        return HTMLResponse(f"Error loading obs overlay: {e}", status_code=500)


def _get_ffmpeg_path():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _video_stream_command(ffmpeg, codec, width, height, fps):
    bitrate = "800k"
    bufsize = "1600k"
    base = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
    ]
    if codec == "h265":
        return base + [
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-b:v",
            bitrate,
            "-maxrate",
            bitrate,
            "-bufsize",
            bufsize,
            "-x265-params",
            f"log-level=error:keyint={fps}:min-keyint={fps}:scenecut=0",
            "-tag:v",
            "hvc1",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "mp4",
            "-movflags",
            "empty_moov+default_base_moof+frag_keyframe",
            "pipe:1",
        ]

    return base + [
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-b:v",
        bitrate,
        "-maxrate",
        bitrate,
        "-bufsize",
        bufsize,
        "-profile:v",
        "baseline",
        "-level",
        "3.1",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(fps),
        "-keyint_min",
        str(fps),
        "-sc_threshold",
        "0",
        "-f",
        "mp4",
        "-movflags",
        "empty_moov+default_base_moof+frag_keyframe",
        "pipe:1",
    ]


async def ws_live_screenshot(websocket):
    await websocket.accept()

    instance = websocket.query_params.get("instance", "alas")
    codec = websocket.query_params.get("codec", "h264").lower()
    if codec not in ("h264", "h265"):
        codec = "h264"
    try:
        fps = int(websocket.query_params.get("fps", "5"))
    except ValueError:
        fps = 5
    fps = max(1, min(fps, 15))
    try:
        target_width = int(websocket.query_params.get("width", "640"))
    except ValueError:
        target_width = 640
    target_width = max(320, min(target_width, 1280))

    ffmpeg = _get_ffmpeg_path()
    if not ffmpeg:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "ffmpeg not found. Install ffmpeg or imageio-ffmpeg to use H264/H265 live preview.",
        }))
        await websocket.close()
        return

    stop_event = threading.Event()
    out_queue = queue.Queue(maxsize=16)
    proc = None

    try:
        from module.webui.fake_pil_module import remove_fake_pil_module
        remove_fake_pil_module()
    except Exception:
        pass

    try:
        from module.config.config import AzurLaneConfig
        from module.device.device import Device

        if "ALAS_CONFIG_NAME" not in os.environ:
            os.environ["ALAS_CONFIG_NAME"] = instance

        config = AzurLaneConfig(instance)
        device = Device(config)
        first = device.screenshot()
        src_height, src_width = first.shape[:2]
        target_height = int(round(target_width * src_height / src_width))
        if target_height % 2:
            target_height += 1
        size = (target_width, target_height)

        mime = (
            'video/mp4; codecs="hvc1.1.6.L93.B0"'
            if codec == "h265"
            else 'video/mp4; codecs="avc1.42E01E"'
        )
        await websocket.send_text(json.dumps({
            "type": "ready",
            "codec": codec,
            "mime": mime,
            "width": target_width,
            "height": target_height,
            "fps": fps,
        }))

        proc = subprocess.Popen(
            _video_stream_command(ffmpeg, codec, target_width, target_height, fps),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        def normalize_frame(image):
            if image.shape[1] != target_width or image.shape[0] != target_height:
                image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
            if not image.flags["C_CONTIGUOUS"]:
                image = image.copy()
            return image

        def writer():
            frame_interval = 1 / fps
            next_frame = time.perf_counter()
            image = first
            while not stop_event.is_set():
                try:
                    proc.stdin.write(normalize_frame(image).tobytes())
                    proc.stdin.flush()
                except Exception:
                    break
                next_frame += frame_interval
                sleep_for = next_frame - time.perf_counter()
                if sleep_for > 0:
                    stop_event.wait(sleep_for)
                if stop_event.is_set():
                    break
                try:
                    image = device.screenshot()
                except Exception as e:
                    out_queue.put(("error", str(e)))
                    break
            try:
                proc.stdin.close()
            except Exception:
                pass

        def reader():
            while not stop_event.is_set():
                try:
                    chunk = proc.stdout.read(32768)
                except Exception:
                    break
                if not chunk:
                    break
                out_queue.put(("data", chunk))
            out_queue.put(("eof", None))

        def stderr_reader():
            try:
                err = proc.stderr.read().decode("utf-8", errors="replace").strip()
            except Exception:
                err = ""
            if err and not stop_event.is_set():
                out_queue.put(("error", err[-1000:]))

        threading.Thread(target=writer, daemon=True).start()
        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=stderr_reader, daemon=True).start()

        while not stop_event.is_set():
            kind, payload = await asyncio.to_thread(out_queue.get)
            if kind == "data":
                await websocket.send_bytes(payload)
            elif kind == "error":
                await websocket.send_text(json.dumps({"type": "error", "message": payload}))
                break
            else:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"ws_live_screenshot error: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass
    finally:
        stop_event.set()
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass

api_routes = [
    Route("/api/cl1_stats", api_cl1_stats),
    Route("/api/ap_timeline", api_ap_timeline),
    Route("/obs", serve_obs_overlay),
    WebSocketRoute("/ws/live_screenshot", ws_live_screenshot),
]
