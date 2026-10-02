import os

from PIL import Image
from tqdm import tqdm

import module.config.server as server

server.server = 'cn'  # 无需修改，用于避免服务器配置未初始化的异常。

from dev_tools.relative_record import FOLDER, NAME
from module.base.utils import *
from module.map_detection.utils import *

"""
通过暴力搜索生成最优塞壬 GIF 动态模板。

使用说明：
    参见 relative_record.py。

参数说明：
    FOLDER:     来自 relative_record 的保存目录。
    NAME:       来自 relative_record 的塞壬名称。
                生成的 GIF 文件保存至 <FOLDER>/<NAME>_gif/<frame_count>_<average_similarity>_<size>.gif。
    THRESHOLD:  去重相似度阈值，高于该阈值的候选帧将被丢弃。
                实际检测阈值为 0.85，为保证提取精度，此处的阈值应高于 0.85。
    MAX_FRAME:  GIF 模板的最大允许帧数。
"""
# 参数 FOLDER 默认从 relative_record.py 导入，如需修改在此处赋值。
# FOLDER = ''
# 参数 NAME 默认从 relative_record.py 导入，如需修改在此处赋值。
# NAME = 'Dace'
THRESHOLD = 0.92
MAX_FRAME = 6


def crop(image, area):
    """在 OpenCV / NumPy 下实现类似 PIL 的图像区域裁剪。

    Args:
        image (np.ndarray): 原始输入图像。
        area (tuple[int, int, int, int]): 裁剪区域 (x1, y1, x2, y2)。

    Returns:
        np.ndarray: 裁剪后的图像数组。
    """
    x1, y1, x2, y2 = area
    return image[y1:y2, x1:x2]


class RelativeRecord:
    """塞壬 GIF 动态模板暴力搜索与生成器。

    Attributes:
        images (np.ndarray): 录制的所有帧图像数组。
        images_amount (int): 图像总帧数。
        folder (str): GIF 模板保存目录。
    """

    def __init__(self):
        """初始化生成器并加载录制的图像序列。"""
        self.images = [np.array(Image.open(os.path.join(FOLDER, NAME, file)).convert('RGB')) for file in
                       os.listdir(os.path.join(FOLDER, NAME))
                       if file[-4:] == '.png']
        self.images = np.array(self.images)
        self.images_amount = len(self.images)
        self.folder = os.path.join(FOLDER, f'{NAME}_gif')
        if not os.path.exists(self.folder):
            os.mkdir(self.folder)

    def count(self, area):
        """计算覆盖所有帧所需的最少模板帧数。

        Args:
            area (tuple[int, int, int, int]): 候选裁剪区域。

        Returns:
            int: 覆盖所需的帧数。
        """
        mask = np.full(self.images_amount, False, dtype=bool)

        template = crop(self.images[0], area=area)
        template_0 = template
        count = 0

        while np.sum(mask) < self.images_amount and count < MAX_FRAME:
            count += 1
            mask_inv = mask == False
            m = [np.max(cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)) > THRESHOLD
                 for image in self.images[mask_inv]]

            mask[mask_inv] |= m

            image = self.images[np.argmin(mask)]
            res = cv2.matchTemplate(image, template_0, cv2.TM_CCOEFF_NORMED)
            _, sim, _, loca = cv2.minMaxLoc(res)
            template = crop(image, area=area_offset(area, np.subtract(loca, area[:2])))

        return count

    def count_by_size(self, size, padding=10):
        """在指定尺寸下网格化搜索满足最大帧数限制的候选区域。

        Args:
            size (tuple[int, int]): 裁剪窗口的 (宽度, 高度)。
            padding (int): 边缘留白像素，默认为 10。

        Returns:
            set[tuple[int, int, int, int]]: 满足条件的裁剪区域集合。
        """
        image_size = self.images[0].shape
        stats = set()
        print('正在 2x2 网格中尝试候选模板')
        area_list = [(x, y, x + size[0], y + size[1])
                     for x in range(padding, image_size[0] - size[0] - padding, 2)
                     for y in range(padding, image_size[1] - size[1] - padding, 2)]
        for area in tqdm(area_list):
                count = self.count(area)
                if count < MAX_FRAME:
                    stats.add(area)

        print('正在生成所有候选模板区域')
        offset_list = np.array([(1, 0, 1, 0), (-1, 0, -1, 0), (0, 1, 0, 1), (0, -1, 0, -1)])
        out = stats.copy()
        visited = set()
        for area in tqdm(stats):
            area = np.array(area)
            for offset in offset_list:
                new = area + offset
                new = tuple(new.tolist())
                if new not in visited and self.count(area=new) < MAX_FRAME:
                    out.add(new)
                visited.add(new)

        return out

    def get_gif(self, area):
        """为指定区域提取动态模板帧序列并计算平均匹配相似度。

        Args:
            area (tuple[int, int, int, int]): 裁剪区域。

        Returns:
            tuple[float, list[np.ndarray]]: (平均相似度, 模板帧列表)。
        """
        templates = [crop(self.images[0], area=area)]
        sim_list = []
        for n, image in enumerate(self.images):
            max_sim = 0
            max_loca = (0, 0)
            for template in templates:
                res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
                _, sim, _, loca = cv2.minMaxLoc(res)
                if sim > max_sim:
                    max_sim = sim
                    max_loca = loca

            if max_sim > THRESHOLD:
                sim_list.append(max_sim)
                continue

            templates.append(crop(image, area=area_offset(area, np.subtract(max_loca, area[:2]))))

        return np.mean(sim_list), templates

    def run_by_size(self, size):
        """针对指定尺寸搜索最佳模板并保存为 GIF 文件。

        Args:
            size (tuple[int, int]): 裁剪区域尺寸 (宽度, 高度)。
        """
        sim_dict = {}
        template_dict = {}
        area_list = self.count_by_size(size)
        print('正在测试所有候选模板')
        for area in tqdm(area_list):
            sim, templates = self.get_gif(area)
            count = len(templates)

            if sim > sim_dict.get(count, 0):
                sim_dict[count] = sim
                template_dict[count] = templates

        print('正在保存 GIF 模板')
        for count, sim, templates in zip(sim_dict.keys(), sim_dict.values(), template_dict.values()):
            sim = str(int((1 - sim) * 1000000)).rjust(6, '0')
            name = f'{count}_{sim}_{"-".join([str(x) for x in size])}'
            file = os.path.join(self.folder, f'{name}.gif')
            # 用 PIL 保存多帧 GIF。imageio.mimsave 在此环境生成的文件
            # 无法被 imageio.mimread 解析（codec configuration error），
            # 而 template.py / button_extract.py 均使用 imageio.mimread 读取。
            frames = [Image.fromarray(template) for template in templates]
            frames[0].save(
                file, save_all=True, append_images=frames[1:],
                duration=1000 / 3, loop=0,
            )
        print(f'{size} 处理完成')


r = RelativeRecord()
r.run_by_size((15, 18))
print('relative_record_gif2 处理完成')
