from module.logger import logger
from module.ocr.ocr import Digit
from module.os_handler.assets import MARITIME_SCHEDULE


class SeaMilesOCR(Digit):
    def __init__(self):
        super().__init__(
            buttons=MARITIME_SCHEDULE,
            lang='azur_lane',
            letter=(255, 207, 66),
            threshold=128,
            alphabet='0123456789',
            name='SEA_MILES'
        )

    def after_process(self, result):
        result = super().after_process(result)
        if not (0 <= result <= 100000000):
            logger.warning(f"Abnormal sea miles: {result}")
            return 0
        return result


OCR_SEA_MILES_DIGIT = SeaMilesOCR()
