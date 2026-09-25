"""经营端「上架前库存校验」独立模块（Add by MHY）。

背景：ALAS 原有逻辑只对**季节限定商品**做仓库库存校验；普通配置商品
（IslandBusinessShopN.Product1-5）在仓库没货时，上架会静默失败——那一格
空着，日志里还显示"选择餐品"，看不出来。

本模块在进入商店之前统一校验一次：
    进仓库截图 → OCR 本店全部商品库存 → 没货的换成「有货且利润更高」的候选

与经营主流程解耦：IslandBusiness 只需继承本 Mixin，并在批次开始前调用
_check_products_stock_for_batch()；替换逻辑 replace_missing_products()
是纯函数，可离线单测。
"""
import os

from module.base.template import Template
from module.island.island_economy import EconomyDatabase
from module.island.warehouse import WarehouseOCR
from module.logger import logger


class BusinessStockCheckMixin:
    """经营端库存校验（依赖宿主类提供 shop_products / active_products / 仓库导航）。"""

    STOCK_MIN = 1  # 低于该库存视为需要替换

    # ---------- 纯逻辑（可离线单测） ----------

    def rank_shop_products(self, shop_name):
        """
        本店可上架商品按利润/分钟降序（经济库缺失的商品排最后，保持原顺序）。

        Args:
            shop_name: 商店中文名

        Returns:
            list[str]
        """
        names = [p['name'] for p in self.shop_products.get(shop_name, [])]
        return EconomyDatabase().sort_by_profit(names)

    def replace_missing_products(self, shop_name, counts):
        """
        按库存数决定上架清单：没货的商品用有货的高利润候选替换。

        Args:
            shop_name: 商店中文名
            counts: {商品英文名: 仓库库存}

        Returns:
            tuple: (new_products, replacements)
                new_products: 替换后的商品条目列表（保持按钮对象）
                replacements: [(缺货商品, 替补商品, 替补库存)]
        """
        products = list(self.active_products.get(shop_name, []))
        if not products:
            return products, []

        ranked = self.rank_shop_products(shop_name)
        # 已在清单里的商品不再作为替补（同一商品占两格没有意义）
        reserved = {p['name'] for p in products}
        used = set()
        new_products = []
        replacements = []

        for item in products:
            name = item['name']
            stock = counts.get(name, 0)
            if stock < 0:
                # 库存未知（没有仓库模板）：保守起见保持原配置
                new_products.append(item)
                used.add(name)
                continue
            if stock >= self.STOCK_MIN:
                new_products.append(item)
                used.add(name)
                continue
            candidate = None
            for cand in ranked:
                if cand in reserved or cand in used:
                    continue
                if counts.get(cand, 0) < self.STOCK_MIN:
                    continue
                found = self._find_product_by_name(shop_name, cand)
                if found is None:
                    continue
                candidate = (found, cand)
                break
            if candidate is None:
                logger.warning(f"[岛屿-库存校验] {shop_name} {name} 无库存且无可替换候选，保持原配置")
                new_products.append(item)
                used.add(name)
                continue
            found, cand = candidate
            new_products.append(found)
            used.add(cand)
            replacements.append((name, cand, counts[cand]))
        return new_products, replacements

    # ---------- 设备交互 ----------

    def _stock_check_template(self, shop_type, name):
        """
        商品 → 仓库识别模板。

        必须用生产端同一套仓库小图（assets/cn/island_<店>/TEMPLATE_<商品>.png）：
        经营端的商品图标（BUSINESS_PRODUCT_*）是货架样式，与仓库图标不同，
        拿去匹配仓库格子相似度只有 0.4 左右，会全部读成 0。

        Args:
            shop_type: 店铺类型标识（restaurant/teahouse/...）
            name: 商品英文名

        Returns:
            Template 或 None（该商品没有仓库模板）
        """
        path = f'./assets/cn/island_{shop_type}/TEMPLATE_{name.upper()}.png'
        if not os.path.exists(path):
            return None
        return Template(file={'cn': path, 'en': path, 'jp': path, 'tw': path})

    def check_configured_products_stock(self, shop_name):
        """
        校验本店配置商品库存并替换缺货项。

        会离开经营页去仓库，调用方负责之后切回经营页签。

        Args:
            shop_name: 商店中文名

        Returns:
            int: 替换数量
        """
        products = list(self.active_products.get(shop_name, []))
        if not products:
            return 0
        shop_type = self.SHOP_SEASON_MAP.get(shop_name, '')
        if not shop_type:
            logger.warning(f"[岛屿-库存校验] 未知商店 {shop_name}，跳过")
            return 0

        logger.info(f"[岛屿-库存校验] {shop_name} 校验配置商品库存")
        # 与生产端一致：只按「来源」筛选（种类=成品+来源的交集会是空列表，导致全读 0）
        self.goto_warehouse_within_postmanage(shop_type, None)
        self.device.sleep(0.5)
        self.device.screenshot()

        # 自带 OCR 实例：经营类不强依赖 WarehouseOCR 基类，保持模块自持
        warehouse = WarehouseOCR()
        counts = {}
        for item in self.shop_products.get(shop_name, []):
            name = item['name']
            template = self._stock_check_template(shop_type, name)
            if template is None:
                counts[name] = -1  # 无仓库模板：库存未知，保持原配置
                continue
            counts[name] = warehouse.ocr_item_quantity(self.device.image, template)

        logger.info(f"[岛屿-库存校验] {shop_name} 读取库存: "
                    f"{ {k: v for k, v in counts.items() if v > 0} }")
        if not any(value > 0 for value in counts.values()):
            # 全 0 说明页面/筛选没到位，读取不可信：保存现场并跳过，不据此改配置
            logger.warning(f"[岛屿-库存校验] {shop_name} 未读到任何库存，跳过本次校验")
            try:
                from PIL import Image
                path = os.path.join('log', f'island_stock_{shop_type}.png')
                Image.fromarray(self.device.image).save(path)
                logger.info(f"[岛屿-库存校验] 现场截图: {path}")
            except Exception:
                logger.warning("[岛屿-库存校验] 现场截图保存失败")
            return 0

        new_products, replacements = self.replace_missing_products(shop_name, counts)
        for missing, candidate, stock in replacements:
            logger.info(f"[岛屿-库存校验] {shop_name} {missing} 无库存，"
                        f"替换为 {candidate}（库存 {stock}）")
        if replacements:
            self.active_products[shop_name] = new_products
        else:
            logger.info(f"[岛屿-库存校验] {shop_name} 配置商品库存充足，无需替换")
        return len(replacements)

    def _check_products_stock_for_batch(self, batch_shops):
        """
        对当前批次的商店逐个校验库存，结束后统一切回经营页签。

        Args:
            batch_shops: 批次商店列表（每项含 'name'）
        """
        if not getattr(self.config, 'IslandBusiness_StockCheck', True):
            return
        for shop in batch_shops:
            # 异常隔离：附加模块出错只跳过本次校验，不能让经营任务挂掉
            # （未处理异常会触发游戏重启→重试→死循环）
            try:
                self.check_configured_products_stock(shop['name'])
            except Exception:
                logger.exception(f"[岛屿-库存校验] {shop['name']} 校验异常，本店按原配置上架")
            # 仓库校验会离开经营页，重新导航回经营页签
            self.goto_postmanage()
            self._switch_to_business_tab()
            self._handle_food_review()
