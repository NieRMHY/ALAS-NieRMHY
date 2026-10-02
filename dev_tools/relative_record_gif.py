import os

import imageio
from PIL import Image

import module.config.server as server

server.server = 'cn'  # 无需修改，用于避免服务器配置未初始化的异常。

from dev_tools.relative_record import FOLDER, NAME
from module.base.utils import *
from module.map_detection.utils import *

"""
使用说明：
    参见 relative_record.py。

参数说明：
    FOLDER:     来自 relative_record 的保存目录。
    NAME:       来自 relative_record 的塞壬名称。
                生成的 GIF 文件保存至 <FOLDER>/TEMPLATE_SIREN_<NAME>.gif。
    AREA:       裁剪区域，例如 (32, 32, 54, 52)。
                选择物体旋转幅度较小的局部特征区域。
    THRESHOLD:  相似度阈值。若候选模板与已有模板的最大相似度高于 THRESHOLD，则丢弃该候选帧。
                实际检测阈值为 0.85，为保证提取精度，此处的去重阈值应高于 0.85。
"""
# FOLDER = ''
# NAME = 'Deutschland'
AREA = (32, 32, 54, 52)
THRESHOLD = 0.92

if __name__ == '__main__':
    images = [np.array(Image.open(os.path.join(FOLDER, NAME, file))) for file in os.listdir(os.path.join(FOLDER, NAME))
              if file[-4:] == '.png']
    templates = [crop(images[0], area=AREA)]


    def match(im):
        """在当前图像中匹配已有模板，返回最高相似度及其匹配坐标。

        Args:
            im (np.ndarray): 待匹配的单通道灰度图像。

        Returns:
            tuple[float, tuple[int, int]]: (最高相似度, 最佳匹配左上角坐标)。
        """
        max_sim = 0
        max_loca = (0, 0)
        for template in templates:
            res = cv2.matchTemplate(im, template, cv2.TM_CCOEFF_NORMED)
            _, sim, _, loca = cv2.minMaxLoc(res)
            if sim > max_sim:
                max_sim = sim
                max_loca = loca

        return max_sim, max_loca


    for n, image in enumerate(images):
        sim, loca = match(image)
        if sim > THRESHOLD:
            continue
        print(f'New template: {n}')
        templates.append(crop(image, area=area_offset(AREA, np.subtract(loca, AREA[:2]))))

    imageio.mimsave(os.path.join(FOLDER, f'TEMPLATE_SIREN_{NAME}.gif'), templates, fps=3)
