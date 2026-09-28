"""NCNN OCR 识别后端。

基于 NCNN 推理框架的文本识别模型，比 ONNX 后端推理速度更快。
NCNN 是一个为移动端优化的高性能神经网络推理框架，
特别适合 CPU 推理场景。

模型规格：
- 输入：3 通道 48x320 的 RGB 图像
- 输出：CTC 解码的文本序列
- 模型文件：.param（网络结构）+ .bin（权重数据）+ 字典文件

所有逻辑模型统一使用通用 PP-OCRv6 的 ncnn 转换版本，仅字典不同。

注意：ncnn 后端不支持文本检测，需要配合 ONNX 检测模型使用。
"""

import atexit
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from rapidocr.ch_ppocr_rec.typings import TextRecOutput
from rapidocr.ch_ppocr_rec.utils import CTCLabelDecode
from rapidocr.utils.load_image import LoadImage
from rapidocr.utils.process_img import resize_image_within_bounds

from module.logger import logger


# 项目根目录和 NCNN 模型目录
REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = REPO_ROOT / "bin/ocr_models/ncnn"
# 模型输入尺寸：3 通道 x 48 高 x 320 宽
REC_IMAGE_SHAPE = (3, 48, 320)
INPUT_NAME = "in0"
OUTPUT_NAME = "out0"


@dataclass(frozen=True)
class NcnnRecModelSpec:
    """NCNN 文本识别模型规格定义。

    Attributes:
        name (str): 规格名称或档位（如 'lite', 'standard', 'pro'）。
        param_path (Path): NCNN 网络结构参数文件路径 (.param)。
        bin_path (Path): NCNN 模型权重二进制文件路径 (.bin)。
        keys_path (Path): 识别字符字典文件路径。
        output_name (str): 模型输出层节点名称。
        disable_fp16 (bool): 是否强制禁用 FP16 精度。默认 False。
    """

    name: str
    param_path: Path
    bin_path: Path
    keys_path: Path
    output_name: str
    disable_fp16: bool = False


# PP-OCRv6 三档 ncnn 转换模型：lite(tiny) / standard(small) / pro(medium)。
def _ncnn_spec(name, param, bin, keys):
    """构建 NcnnRecModelSpec 模型规格实例。

    Args:
        name (str): 规格名称。
        param (str): .param 文件名。
        bin (str): .bin 文件名。
        keys (str): 字典文件名。

    Returns:
        NcnnRecModelSpec: 构建完成的模型规格对象。
    """
    return NcnnRecModelSpec(
        name=name,
        param_path=MODEL_ROOT / param,
        bin_path=MODEL_ROOT / bin,
        keys_path=REPO_ROOT / "bin/ocr_models/ppocr-v6" / keys,
        output_name=OUTPUT_NAME,
        disable_fp16=True,
    )


PPOCR_V6_LITE = _ncnn_spec("lite", "ppocr_v6_lite.param", "ppocr_v6_lite.bin", "ppocrv6_tiny_dict.txt")
PPOCR_V6_STANDARD = _ncnn_spec("standard", "ppocr_v6_standard.param", "ppocr_v6_standard.bin", "ppocrv6_dict.txt")
PPOCR_V6_PRO = _ncnn_spec("pro", "ppocr_v6_pro.param", "ppocr_v6_pro.bin", "ppocrv6_dict.txt")
# azur_lane/azur_lane_jp 使用受限 en 字典，将非 en 输出静默过滤。
PPOCR_V6_LITE_EN = _ncnn_spec("lite", "ppocr_v6_lite.param", "ppocr_v6_lite.bin", "ppocrv6_tiny_en_restricted_dict.txt")
PPOCR_V6_STANDARD_EN = _ncnn_spec("standard", "ppocr_v6_standard.param", "ppocr_v6_standard.bin", "ppocrv6_en_restricted_dict.txt")
PPOCR_V6_PRO_EN = _ncnn_spec("pro", "ppocr_v6_pro.param", "ppocr_v6_pro.bin", "ppocrv6_en_restricted_dict.txt")

# MODEL_SPECS[逻辑模型][档位] -> NcnnRecModelSpec。
MODEL_SPECS = {
    "azur_lane": {
        "lite": PPOCR_V6_LITE_EN,
        "standard": PPOCR_V6_STANDARD_EN,
        "pro": PPOCR_V6_PRO_EN,
    },
    "azur_lane_jp": {
        "lite": PPOCR_V6_LITE_EN,
        "standard": PPOCR_V6_STANDARD_EN,
        "pro": PPOCR_V6_PRO_EN,
    },
    "ppocr_v6": {
        "lite": PPOCR_V6_LITE,
        "standard": PPOCR_V6_STANDARD,
        "pro": PPOCR_V6_PRO,
    },
    "cn": {
        "lite": PPOCR_V6_LITE,
        "standard": PPOCR_V6_STANDARD,
        "pro": PPOCR_V6_PRO,
    },
    "jp": {
        "lite": PPOCR_V6_LITE,
        "standard": PPOCR_V6_STANDARD,
        "pro": PPOCR_V6_PRO,
    },
    "tw": {
        "lite": PPOCR_V6_LITE,
        "standard": PPOCR_V6_STANDARD,
        "pro": PPOCR_V6_PRO,
    },
}

MODEL_ALIASES = {
    "ppocr-v6": "ppocr_v6",
    "cnocr": "cn",
    "en": "azur_lane",
    "zhcn": "cn",
}


_ncnn = None
_ncnn_lock = threading.Lock()
_gpu_lock = threading.Lock()
_gpu_instance_created = False


def normalize_model_name(name: str) -> str:
    """标准化 OCR 模型名称别名。

    Args:
        name (str): 原始模型名称。

    Returns:
        str: 标准化后的模型名称。
    """
    return MODEL_ALIASES.get(name, name)


def supports_ncnn_model(name: str) -> bool:
    """检查是否支持指定的 NCNN 模型。

    Args:
        name (str): 模型名称。

    Returns:
        bool: 若支持该模型则返回 True，否则返回 False。
    """
    return normalize_model_name(name) in MODEL_SPECS


def _load_ncnn():
    """按需延迟导入并返回全局 ncnn 模块。

    Returns:
        module: 导入的 ncnn 模块对象。

    Raises:
        RuntimeError: 当未安装 ncnn 依赖包时抛出。
    """
    global _ncnn
    if _ncnn is not None:
        return _ncnn

    with _ncnn_lock:
        if _ncnn is None:
            try:
                import ncnn
            except ImportError as exc:
                raise RuntimeError(
                    "Python package 'ncnn' is required for OCR recognition."
                ) from exc
            _ncnn = ncnn
    return _ncnn


_gpu_instance_registered = False


def _destroy_gpu_instance():
    """atexit 处理函数：安全销毁全局 ncnn GPU 实例。"""
    global _gpu_instance_created, _gpu_instance_registered
    try:
        ncnn = _load_ncnn()
        destroy = getattr(ncnn, "destroy_gpu_instance", None)
        if destroy is not None and _gpu_instance_created:
            destroy()
            _gpu_instance_created = False
    except Exception:
        pass


def _ensure_gpu_instance(ncnn) -> None:
    """确保 ncnn 全局 GPU 实例已创建并注册退出清理。

    Args:
        ncnn (module): ncnn 模块对象。
    """
    global _gpu_instance_created, _gpu_instance_registered
    if _gpu_instance_created:
        return

    with _gpu_lock:
        if not _gpu_instance_created:
            create_gpu_instance = getattr(ncnn, "create_gpu_instance", None)
            if create_gpu_instance is not None:
                create_gpu_instance()
                if not _gpu_instance_registered:
                    atexit.register(_destroy_gpu_instance)
                    _gpu_instance_registered = True
            _gpu_instance_created = True


def get_ncnn_vulkan_gpu_count() -> int:
    """获取系统检测到的支持 Vulkan 的 GPU 数量。

    Returns:
        int: Vulkan GPU 数量。
    """
    ncnn = _load_ncnn()
    _ensure_gpu_instance(ncnn)

    get_gpu_count = getattr(ncnn, "get_gpu_count", None)
    if get_gpu_count is None:
        return 0
    return int(get_gpu_count())


def has_ncnn_vulkan_gpu() -> bool:
    """检查系统是否存在可用的 ncnn Vulkan GPU。

    Returns:
        bool: 存在可用 Vulkan GPU 时返回 True，否则返回 False。
    """
    try:
        return get_ncnn_vulkan_gpu_count() > 0
    except Exception as e:
        logger.warning(f"ncnn Vulkan GPU detection failed: {e}")
        return False


def _resolve_gpu_index(ncnn, requested_index: int) -> int:
    """验证并解析请求的 Vulkan GPU 设备索引。

    Args:
        ncnn (module): ncnn 模块对象。
        requested_index (int): 请求的 GPU 索引，负数表示使用默认 GPU。

    Returns:
        int: 有效的 GPU 索引编号。

    Raises:
        RuntimeError: 未检测到 GPU 或请求的索引超出有效范围。
    """
    gpu_count = get_ncnn_vulkan_gpu_count()
    if gpu_count <= 0:
        raise RuntimeError("ncnn Vulkan requested, but no Vulkan GPU was detected.")

    if requested_index < 0:
        get_default_gpu_index = getattr(ncnn, "get_default_gpu_index", None)
        requested_index = get_default_gpu_index() if get_default_gpu_index else 0

    if not 0 <= requested_index < gpu_count:
        raise RuntimeError(
            f"ncnn Vulkan GPU index {requested_index} is out of range; "
            f"detected {gpu_count} GPU(s)."
        )
    return requested_index


def _gpu_info_value(ncnn, gpu_index: int, name: str):
    """读取指定 GPU 的硬件信息属性值。

    Args:
        ncnn (module): ncnn 模块对象。
        gpu_index (int): GPU 设备索引。
        name (str): 属性名称。

    Returns:
        Any: 属性值；若获取失败则返回 None。
    """
    try:
        info = ncnn.get_gpu_info(gpu_index)
        value = getattr(info, name)
        return value() if callable(value) else value
    except Exception:
        return None


class RecPreprocessor:
    """NCNN 文本识别模型图像预处理器。

    Attributes:
        rec_image_shape (tuple[int, int, int]): 模型期望的输入图像形状 (C, H, W)。
    """

    def __init__(self, rec_image_shape: tuple[int, int, int] = REC_IMAGE_SHAPE):
        """初始化预处理器。

        Args:
            rec_image_shape (tuple[int, int, int]): 输入图像形状 (C, H, W)。
        """
        self.rec_image_shape = rec_image_shape

    def resize_norm_img(self, img: np.ndarray) -> np.ndarray:
        """缩放并归一化图像以适应模型输入规范。

        Args:
            img (np.ndarray): 输入图像，形状为 (H, W, C)。

        Returns:
            np.ndarray: 填充归一化后的图像数组，形状为 (C, H, W)。

        Raises:
            ValueError: 图像通道数与期望通道数不符。
        """
        img_channel, img_height, img_width = self.rec_image_shape
        if img.shape[2] != img_channel:
            raise ValueError(f"Expected {img_channel} channels, got {img.shape[2]}")

        h, w = img.shape[:2]
        ratio = w / float(h)
        resized_w = min(img_width, int(math.ceil(img_height * ratio)))

        resized_image = cv2.resize(img, (resized_w, img_height))
        resized_image = resized_image.astype("float32")
        resized_image = resized_image.transpose((2, 0, 1)) / 255.0
        resized_image -= 0.5
        resized_image /= 0.5

        padding_im = np.zeros((img_channel, img_height, img_width), dtype=np.float32)
        padding_im[:, :, :resized_w] = resized_image
        return padding_im


class NcnnRecOCR:
    """基于 NCNN 框架的文本识别器。

    Attributes:
        spec (NcnnRecModelSpec): 模型规格。
        device (str): 运行设备 ('cpu' 或 'gpu')。
        gpu_index (int): Vulkan GPU 索引。
        use_vulkan (bool): 是否启用 Vulkan 计算加速。
        ncnn (module): ncnn 模块。
        preprocess (RecPreprocessor): 图像预处理器。
        load_image (LoadImage): 图像加载工具。
        decoder (CTCLabelDecode): CTC 解码器。
        class_count (int): 类别字典大小。
        net (ncnn.Net | None): NCNN 神经网络实例。
    """

    def __init__(self, model_name: str, device: str = "cpu", gpu_index: int = -1, version: str = "standard"):
        """初始化 NCNN 识别器。

        Args:
            model_name (str): 模型名称。
            device (str): 目标设备，'cpu' 或 'gpu'。
            gpu_index (int): GPU 设备索引，-1 表示自动选择。
            version (str): 模型版本档位 ('lite', 'standard', 'pro')。

        Raises:
            ValueError: 不支持的模型名称。
        """
        normalized_name = normalize_model_name(model_name)
        specs = MODEL_SPECS.get(normalized_name)
        if specs is None:
            raise ValueError(f"Unsupported ncnn OCR model: {model_name}")
        if version not in specs:
            version = "standard"

        self.spec = specs[version]
        self.device = device
        self.gpu_index = gpu_index
        self.use_vulkan = False
        self.ncnn = _load_ncnn()
        self.preprocess = RecPreprocessor()
        self.load_image = LoadImage()
        self.decoder = CTCLabelDecode(character_path=self.spec.keys_path)
        self.class_count = len(self.decoder.character)
        self.net = None

        self._check_model_files()
        self._create_net()

    def _check_model_files(self) -> None:
        """检查所需模型文件与字典文件是否存在。

        Raises:
            FileNotFoundError: 模型或字典文件缺失。
        """
        missing = [
            str(path)
            for path in (self.spec.param_path, self.spec.bin_path, self.spec.keys_path)
            if not path.is_file()
        ]
        if missing:
            raise FileNotFoundError(
                "Missing ncnn OCR model files: " + ", ".join(missing)
            )

    def _create_net(self) -> None:
        """创建并初始化 NCNN 神经网络与模型参数。

        Raises:
            RuntimeError: 不支持的设备或模型加载失败。
        """
        if self.device == "gpu":
            self.gpu_index = _resolve_gpu_index(self.ncnn, self.gpu_index)
            self.use_vulkan = True
        elif self.device == "cpu":
            self.use_vulkan = False
        else:
            raise RuntimeError(f"Unsupported OCR device for ncnn: {self.device}")

        self.net = self.ncnn.Net()
        if hasattr(self.net, "opt"):
            self.net.opt.use_vulkan_compute = self.use_vulkan
            if self.spec.disable_fp16:
                self.net.opt.use_fp16_packed = False
                self.net.opt.use_fp16_storage = False
                self.net.opt.use_fp16_arithmetic = False

        if self.use_vulkan and hasattr(self.net, "set_vulkan_device"):
            self.net.set_vulkan_device(self.gpu_index)

        self._check_return(
            self.net.load_param(str(self.spec.param_path)),
            "load_param",
            self.spec.param_path,
        )
        self._check_return(
            self.net.load_model(str(self.spec.bin_path)),
            "load_model",
            self.spec.bin_path,
        )

        if self.use_vulkan:
            gpu_name = _gpu_info_value(self.ncnn, self.gpu_index, "device_name")
            backend = f"Vulkan GPU {self.gpu_index}"
            if gpu_name:
                backend = f"{backend} ({gpu_name})"
        else:
            backend = "CPU"
        logger.info(f"[OCR-NCNN] 已加载ncnnOCR模型 '{self.spec.name}' 在 {backend}")

    @staticmethod
    def _check_return(value, op: str, path: Path) -> None:
        """检查 NCNN C++ API 调用返回值状态。

        Args:
            value (int): API 返回的状态码。
            op (str): 操作名称。
            path (Path): 操作相关的文件路径。

        Raises:
            RuntimeError: 返回非零错误码。
        """
        if isinstance(value, int) and value != 0:
            raise RuntimeError(f"ncnn {op} failed for {path}, return code {value}")

    def close(self) -> None:
        """释放网络资源。"""
        self.net = None

    def __call__(self, image_or_path) -> TextRecOutput:
        """执行单图文本识别推理。

        Args:
            image_or_path: 输入图像数据（ndarray、PIL Image 或路径）。

        Returns:
            TextRecOutput: 包含识别文本、置信度及耗时信息的输出对象。
        """
        start_time = time.perf_counter()
        img = self.load_image(image_or_path)
        img, _, _ = resize_image_within_bounds(img, 30, 2000)

        norm = self.preprocess.resize_norm_img(img)
        preds = self._infer(norm)
        line_results, _ = self.decoder(preds)
        text = line_results[0][0]
        score = float(line_results[0][1]) if len(line_results[0]) > 1 else 0.0
        return TextRecOutput(
            imgs=[img],
            txts=(text,),
            scores=(score,),
            word_results=(),
            elapse=time.perf_counter() - start_time,
        )

    def _infer(self, input_arr: np.ndarray) -> np.ndarray:
        """执行前向推理提取网络输出。

        Args:
            input_arr (np.ndarray): 预处理后的图像数组 (C, H, W)。

        Returns:
            np.ndarray: 规范化形状的预测特征数组。

        Raises:
            RuntimeError: 模型已关闭或提取失败。
        """
        if self.net is None:
            raise RuntimeError("ncnn OCR model has been closed")

        ex = self.net.create_extractor()
        mat_in = self._to_ncnn_mat(input_arr)
        ret = ex.input(INPUT_NAME, mat_in)
        if isinstance(ret, int) and ret != 0:
            raise RuntimeError(f"ncnn input('{INPUT_NAME}') failed with code {ret}")

        extracted = ex.extract(self.spec.output_name)
        if isinstance(extracted, tuple):
            status, mat_out = extracted
            if isinstance(status, int) and status != 0:
                raise RuntimeError(
                    f"ncnn extract('{self.spec.output_name}') failed with code {status}"
                )
        else:
            mat_out = extracted

        return self._normalize_output(np.array(mat_out))

    def _to_ncnn_mat(self, input_arr: np.ndarray):
        """将 numpy 数组转换为 ncnn.Mat 格式。

        Args:
            input_arr (np.ndarray): 输入数组 (C, H, W)。

        Returns:
            ncnn.Mat: 转换后的 ncnn 矩阵。

        Raises:
            ValueError: 数组维度不是 3 维。
        """
        arr = np.ascontiguousarray(input_arr, dtype=np.float32)
        if arr.ndim != 3:
            raise ValueError(f"Expected CHW input for ncnn, got shape {arr.shape}")

        c, h, w = arr.shape
        mat = self.ncnn.Mat()
        mat.create(w, h, c)
        mat.numpy("f")[...] = arr
        return mat

    def _normalize_output(self, output: np.ndarray) -> np.ndarray:
        """标准化模型输出维度以匹配 CTC 解码输入。

        Args:
            output (np.ndarray): 原始网络输出数组。

        Returns:
            np.ndarray: 标准化后的输出数组 (batch, seq_len, num_classes)。

        Raises:
            RuntimeError: 输出维度形状无法识别。
        """
        arr = np.asarray(output, dtype=np.float32)

        if arr.ndim == 3 and arr.shape[-1] == self.class_count:
            return arr
        if arr.ndim == 2 and arr.shape[-1] == self.class_count:
            return arr[np.newaxis, :, :]
        if arr.ndim == 2 and arr.shape[0] == self.class_count:
            return arr.T[np.newaxis, :, :]
        if arr.ndim == 3 and arr.shape[0] == self.class_count:
            return np.moveaxis(arr, 0, -1).reshape(1, -1, self.class_count)

        raise RuntimeError(
            "Unable to interpret ncnn output shape "
            f"{arr.shape}; expected class dimension {self.class_count}."
        )
