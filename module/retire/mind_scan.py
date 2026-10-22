"""复用 AP 设备和船坞导航的心智单元扫描任务。"""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import module.config.server as server
from module.base.timer import Timer
from module.base.utils import color_similarity_2d
from module.exception import GameStuckError, MindCalculatorScanError
from module.logger import logger
from module.retire.assets import DOCK_EMPTY
from module.retire.dock import CARD_GRIDS, DOCK_SCROLL, Dock
from module.runtime.mind_calculator import RESULT_PATH, calculate, revision
from module.runtime.mind_recognition import Card, ScanMerger, ScanPolicy, ScrollMotion, grid_rows, recognize_cards
from module.ui.page import page_dock


class MindCalculatorScan(Dock):
    evidence_folder = 'mind_scan'
    scan_label = '心智扫描'

    def _make_merger(self):
        return ScanMerger()

    def _read_cards(self, image, source, names, levels):
        return recognize_cards(image, source, name_ocr=names, level_ocr=levels)

    def _check_scan_page(self, cards, at_bottom):
        """检查已加载行列；真实末页允许最后一排末尾不足七艘。"""
        rows = sorted({card.y for card in cards})
        columns = [{card.col for card in cards if card.y == y} for y in rows]
        if (not columns or any(cols != set(range(7)) for cols in columns[:-1])
                or columns[-1] != set(range(len(columns[-1])))
                or not at_bottom and (len(rows) != 3 or len(cards) != 21)):
            raise ValueError('扫描卡片未完整加载或存在缺格')

    def run(self):
        """扫描指定等级范围；三排确认低于下限后结束，完成前保留旧结果。

        Pages:
            in: Any
            out: page_dock
        """
        if server.server != 'cn':
            raise MindCalculatorScanError('心智单元计算器当前内置国服舰船资料，请在国服实例使用自动扫描')
        from module.ocr.al_ocr import AlOcr
        from module.config.deep import deep_get, deep_set
        from module.config.transaction import config_transaction
        from module.config.utils import filepath_config
        logger.hr('心智单元船坞扫描', level=0)
        logger.attr('心智扫描源码', f'{Path(__file__).resolve()} SHA256 {sha256(Path(__file__).read_bytes()).hexdigest()}')
        self._scan_evidence_paths = set()
        try:
            self._policy = ScanPolicy(self.config.MindCalculator_MinLevel, self.config.MindCalculator_MaxLevel,
                                      sorted_desc=True)
        except ValueError as exc:
            raise MindCalculatorScanError(str(exc)) from exc
        logger.attr('扫描等级范围', f'{self._policy.min_level}–{self._policy.max_level}（含边界）')
        previous_revision = revision(deep_get(self.config.data, RESULT_PATH, {}).get('ships', []))
        self.ui_ensure(page_dock)
        self.dock_reset()
        # 通用 reset 服务于退役的升序流程；本任务需要明确切换为等级降序。
        self.dock_sort_method_dsc_set(True)
        if self.appear(DOCK_EMPTY):
            ships = []
        else:
            DOCK_SCROLL.set_top(self)
            if DOCK_SCROLL.appear(self):
                if DOCK_SCROLL.at_top(self) or DOCK_SCROLL.length == DOCK_SCROLL.total:
                    logger.attr('船坞位置', '已确认顶部')
                else:
                    raise MindCalculatorScanError('船坞未能回到顶部，保留旧扫描结果')
            else:
                raise MindCalculatorScanError('无法识别船坞滚动条，保留旧扫描结果')
            try:
                names = AlOcr(config=self.config, name='ppocr_v6', save_debug_images=False)
                levels = AlOcr(config=self.config, name='azur_lane', save_debug_images=False)
                ships = self._scan_pages(names, levels)
            except MemoryError as exc:
                raise MindCalculatorScanError('扫描内存不足，已停止并保留旧清单；请释放内存后重试') from exc
        # 扫描期间用户可能修改数据；复读当前配置避免覆盖手工修正。
        with config_transaction(filepath_config(self.config.config_name)):
            latest = self.config.read_file(self.config.config_name)
            if revision(deep_get(latest, RESULT_PATH, {}).get('ships', [])) != previous_revision:
                raise MindCalculatorScanError('扫描期间舰船数据已修改，保留现有数据；请重新扫描')
            # 同一清单重复保存只会更新日期；通过版本检查后更新本字段基线，
            # 让通用配置保存继续保护其他字段，同时允许提交已完成的扫描。
            if hasattr(self.config, '_loaded_data'):
                import copy
                deep_set(self.config._loaded_data, RESULT_PATH, copy.deepcopy(deep_get(latest, RESULT_PATH, {})))
            self.config.modified[RESULT_PATH] = dict(ships=ships, updated_at=datetime.now().isoformat(timespec='seconds'))
            self.config.save()
        self._prune_scan_evidence()
        result = calculate(ships)
        logger.info(f'[心智扫描] 已保存 {len(ships)} 艘，计入 {result["included"]} 艘，'
                    f'待核对 {result["review"]} 艘，心智单元Ⅰ {result["mind"]}，物资 {result["gold"]}')

    @staticmethod
    def _stable_pixels(image):
        """比较等级、名字和滚动条，避免卡面动态闪光阻止稳定检测。"""
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        rows = grid_rows(image)
        if not rows:
            return gray[65:640, 80:1250]
        signature = np.zeros(gray.shape, dtype=np.uint8)
        for y in rows:
            signature[y:y + 32, 85:1225] = gray[y:y + 32, 85:1225]
            signature[y + 155:y + 185, 85:1225] = gray[y + 155:y + 185, 85:1225]
        signature[55:715, 1238:1250] = gray[55:715, 1238:1250]
        return signature

    def _save_scan_evidence(self, image):
        """保存核对原帧；诊断写盘失败不影响扫描继续。"""
        from time import time_ns
        path = Path(logger.log_file or 'log/alas.txt').parent / self.evidence_folder / self.config.config_name / f'{time_ns()}.png'
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path)
            if not hasattr(self, '_scan_evidence_paths'):
                self._scan_evidence_paths = set()
            self._scan_evidence_paths.add(path.resolve())
            logger.attr('扫描核对原帧', str(path))
            return str(path)
        except OSError as exc:
            logger.warning(f'扫描核对原帧保存失败，继续新截图核对：{exc}')
            return ''

    def _prune_scan_evidence(self):
        """成功提交后只保留本轮诊断；停止或冲突时不删除旧清单的原帧。"""
        if Path(f'cache/{self.evidence_folder.replace("_", "-")}-diagnostics').is_file():
            return
        log_root = Path(logger.log_file or 'log/alas.txt').parent.resolve()
        root = log_root / self.evidence_folder / self.config.config_name
        try:
            root = root.resolve()
            root.relative_to(log_root / self.evidence_folder)
            if not root.is_dir():
                return
            current = {path.stem for path in getattr(self, '_scan_evidence_paths', set())}
            for path in root.iterdir():
                # 只处理本工具的 time_ns 文件，不递归或清理普通日志、其他实例。
                if (path.suffix not in ('.png', '.json') or len(path.stem) != 19
                        or not path.stem.isdecimal() or path.stem in current or not path.is_file()):
                    continue
                path.resolve().relative_to(root)
                path.unlink()
        except (OSError, ValueError) as exc:
            logger.warning(f'旧扫描诊断清理失败，已保留扫描结果：{exc}')

    def _drag_rows(self, distance):
        """一次最多拖一排行距，终点按住后释放，截图再确认实际位移。"""
        # 游戏开始滚动前会消耗一段触控距离；实机 13px 校正可能完全不动。
        # 小距离增加一次路径点的距离，是否到位仍由下一帧的卡片位置核实。
        supported = self.config.Emulator_ControlMethod in ('minitouch', 'MaaTouch', 'uiautomator2', 'scrcpy', 'nemu_ipc')
        if supported and 0 < abs(distance) < 64:
            distance += 20 if distance > 0 else -20
        start = (1170, 470) if distance > 0 else (1170, 243)
        end = (start[0], start[1] - distance)
        if supported:
            self.device.drag(start, end, point_random=(0, 0, 0, 0), shake=(0, 0),
                             shake_random=(0, 0, 0, 0), hold_duration=.4, name='心智单元船坞三排定位')
        else:
            if abs(distance) < 10:
                raise MindCalculatorScanError('当前控制方式无法进行船坞小距离校正，请改用 MaaTouch 等支持拖拽的控制方式')
            # 不使用 Device.drag 的不支持分支，避免其松手后回退点击舰船。
            self.device.swipe(start, end, duration=.6, name='心智单元船坞三排定位')
        return distance, supported

    def _dock_scroll_thumb(self):
        """核实滑块连续性，仅容许一个颜色恰在阈值上的内部采样缺口。"""
        if not DOCK_SCROLL.appear(self):
            raise MindCalculatorScanError('无法识别船坞滚动条，保留旧扫描结果')
        mask = np.asarray(DOCK_SCROLL.match_color(self), dtype=bool)
        thumb = np.flatnonzero(mask)
        if len(thumb):
            gaps = np.flatnonzero(~mask[thumb[0]:thumb[-1] + 1]) + thumb[0]
            if not len(gaps):
                return thumb
            if len(gaps) == 1:
                # 只在一个阈值边界行内补抗锯齿像素，前后行仍用严格颜色。
                # 三行须八邻接连通，不用固定横向跨度猜圆角的采样相位。
                gap = gaps[0]
                pixels = self.image_crop(DOCK_SCROLL.area, copy=False)[gap - 1:gap + 2]
                scores = color_similarity_2d(pixels, color=DOCK_SCROLL.color)
                above = np.flatnonzero(scores[0] > DOCK_SCROLL.color_threshold)
                bridge = np.flatnonzero(scores[1] >= DOCK_SCROLL.color_threshold - 3)
                below = np.flatnonzero(scores[2] > DOCK_SCROLL.color_threshold)
                if (scores[1].max() == DOCK_SCROLL.color_threshold
                        and any(np.any(abs(above - col) <= 1) and np.any(abs(below - col) <= 1) for col in bridge)):
                    return np.arange(thumb[0], thumb[-1] + 1)
        raise MindCalculatorScanError('船坞滚动条被遮挡，无法确认底部，保留旧扫描结果')

    def _recover_page_cards(self, image, cards, at_bottom):
        """有可靠行位和同排实际卡片证据时，将局部缺格保留为未知卡位。"""
        rows = grid_rows(np.array(image))
        if not cards or not rows or not at_bottom and len(rows) != 3:
            return None
        if any(not any(card.y == y for card in cards) for y in rows):
            return None
        recovered = list(cards)
        for y in rows:
            present = {card.col for card in cards if card.y == y}
            end = max(present) + 1 if at_bottom and y == rows[-1] else 7
            for col in set(range(end)) - present:
                x = round(float(CARD_GRIDS.origin[0] + col * CARD_GRIDS.delta[0]))
                recovered.append(Card(x, y, col, dict(
                    name=f'待核对舰船（{y}px 第 {col + 1} 列）', level=0, rarity='', base_rarity='',
                    excluded=False, review=True, group_type=None, type=None, candidates=[], identity_ambiguous=True,
                    source='当前卡位三帧仍未加载，保留位置待核对'), fleet=-1))
        return sorted(recovered, key=lambda card: (card.y, card.col))

    def _dock_scroll_at_bottom(self, thumb):
        """严格滑块或与其连通、收窄到轨道末端的圆角端帽证明到底。"""
        if thumb is None:
            return False
        if thumb[-1] >= DOCK_SCROLL.total - 2:
            return True
        if thumb[-1] != DOCK_SCROLL.total - 3:
            return False
        # 原生圆角的最后两行受抗锯齿混色影响，可能低于严格阈值。
        # 仅核对轨道末端两行的正向颜色、逐行收窄及八邻接；不扩展
        # 滑块读数或改变运动标定，也不把静止、近底部当作到底。
        pixels = self.image_crop(DOCK_SCROLL.area, copy=False)[-3:]
        scores = color_similarity_2d(pixels, color=DOCK_SCROLL.color)
        cap = scores >= DOCK_SCROLL.color_threshold - 18
        widths = cap.sum(axis=1)
        if not widths[0] > widths[1] > widths[2] >= 1:
            return False
        connected = np.flatnonzero(scores[0] > DOCK_SCROLL.color_threshold)
        for row in cap[1:]:
            connected = np.array([col for col in np.flatnonzero(row) if np.any(abs(connected - col) <= 1)])
        return bool(len(connected))

    def _scan_pages(self, names, levels):
        """分段核验三排位移，目标位置连续稳定后识别整页，末页确认到底。"""
        merger = self._make_merger()
        motion, last_drag = ScrollMotion(), None
        motion_retries = scroll_failures = 0
        diagnostic_pages = Path(f'cache/{self.evidence_folder.replace("_", "-")}-diagnostics').is_file()
        policy = getattr(self, '_policy', ScanPolicy(95, 125))
        previous = None
        stable = Timer(.6, count=3).start()
        drag = Timer(.8).start()
        target = pitch = origin_y = None
        attempts = 0
        read_attempts = 0
        evidence_path = ''
        evidence_frame = None
        last_page_image = None
        page = 0
        progress = Timer(20, count=10).start()
        waiting = Timer(30).start()
        while True:
            self.device.screenshot()
            # 所有前置分支都经过期限检查，动画、页面丢失或反复弹窗不能无限续期。
            if waiting.reached():
                raise MindCalculatorScanError('船坞画面 30 秒内未能稳定或页面已丢失，保留旧扫描结果')
            if page and not read_attempts and progress.reached():
                raise GameStuckError('船坞扫描画面没有继续滚动，尚未确认到底')
            if self.appear(page_dock.check_button):
                pixels = self._stable_pixels(self.device.image)
                # 保留全像素平均差及原阈值，避免整帧浮点转换产生大块临时分配。
                if (previous is None or pixels.shape != previous.shape
                        or cv2.mean(cv2.absdiff(pixels, previous))[0] > 1):
                    previous = pixels.copy()
                    stable.reset()
                    continue
                if not stable.reached():
                    continue
                waiting.reset()
                image = Image.fromarray(self.device.image)
                try:
                    thumb = self._dock_scroll_thumb()
                    scroll_failures = 0
                except MindCalculatorScanError:
                    thumb = None
                    scroll_failures += 1
                    if scroll_failures in (1, 3):
                        logger.warning('船坞滚动条暂未确认，继续核验卡片位移，本帧不据此判断到底')
                try:
                    moved = merger.advance(image, bounds=motion.bounds(thumb, last_drag), after_drag=last_drag is not None)
                except ValueError as exc:
                    motion_retries += 1
                    if motion_retries < 3:
                        logger.warning(f'当前滚动位移待确认，重新截图核对（{motion_retries}/3）')
                        previous = None
                        stable.reset()
                        waiting.reset()
                        continue
                    raise MindCalculatorScanError(str(exc)) from exc
                motion_retries = 0
                if merger.motion_hint_used:
                    logger.attr('重复卡片位移核验', f'{moved:+d}px，已结合独立滑块运动确认')
                motion.accept(thumb, moved, hinted=merger.motion_hint_used)
                last_drag = None
                if moved:
                    progress.reset()
                    # 只有已核实的位移才清除连击历史，停滞仍沿用设备检测和超时恢复。
                    self.device.click_record_clear()
                    logger.attr('船坞实际位移', f'{moved:+d}px，累计 {merger.offset}px')
                at_bottom = self._dock_scroll_at_bottom(thumb)
                visible_rows = grid_rows(self.device.image)
                aligned = (target is not None and len(visible_rows) == 3
                           and abs(visible_rows[0] + merger.offset - origin_y - target) <= 6)
                if target is None or aligned or abs(target - merger.offset) <= 3 or at_bottom:
                    try:
                        cards = []
                        try:
                            cards = self._read_cards(image, f'自动扫描第 {page + 1} 页', names, levels)
                            self._check_scan_page(cards, at_bottom)
                        except ValueError:
                            read_attempts += 1
                            if read_attempts < 3:
                                logger.warning(f'当前页卡片未完整加载，重新截图核对（{read_attempts}/3）')
                                previous = None
                                stable.reset()
                                waiting.reset()
                                continue
                            cards = self._recover_page_cards(image, cards, at_bottom)
                            if cards is None:
                                raise
                            self._check_scan_page(cards, at_bottom)
                            read_attempts = 2
                            logger.warning('当前页局部缺格已保留为待核对卡位，继续处理其余舰船')
                        invalid = [card for card in cards if not card.level_reliable]
                        uncertain_names = [card for card in cards if card.ship['review'] and card.level_reliable
                                           and not (card.identity_ambiguous or card.ship.get('identity_ambiguous'))]
                        uncertain_fleets = [card for card in cards if card.fleet < 0]
                        # 复核本页与前一船位的边界；历史疑点保留在原卡位，
                        # 不让单点读数问题持续污染后续完整页面的早停证据。
                        current_slots = [[card, card.y + merger.offset] for card in cards]
                        first = min((y, card.col) for card, y in current_slots)
                        preceding = [slot for slot in merger.slots if (slot[1], slot[0].col) < first]
                        boundary = max(preceding, key=lambda slot: (slot[1], slot[0].col)) if preceding else None
                        candidate_slots = current_slots
                        if boundary and boundary[0].level_reliable and boundary[0].fleet >= 0:
                            candidate_slots = [boundary, *current_slots]
                        order_issue = policy.sort_issue(candidate_slots)
                        if invalid or uncertain_names or uncertain_fleets or order_issue:
                            read_attempts += 1
                            locations = order_issue or '、'.join(f'{card.y}px 行第 {card.col + 1} 列'
                                                               for card in invalid or uncertain_names or uncertain_fleets)
                            reason = '等级' if invalid else '舰名/身份' if uncertain_names else '编队/排序'
                            if (uncertain_fleets or order_issue) and read_attempts == 1:
                                logger.attr('编队复核标记', ','.join(str(card.fleet) for card in cards))
                                evidence_path = self._save_scan_evidence(image)
                                evidence_frame = image
                            if read_attempts >= 3:
                                # 核对项对应最终接受的新帧；首次冲突原帧仍单独保留作诊断。
                                evidence_path = self._save_scan_evidence(image)
                                evidence_frame = image
                                affected = [(card, '等级未确认') for card in invalid]
                                affected += [(card, '舰名/身份未确认') for card in uncertain_names]
                                affected += [(card, '编队标记未确认') for card in uncertain_fleets]
                                if order_issue:
                                    affected += policy.sort_conflicts(candidate_slots)
                                positions = {id(card): y for card, y in merger.slots}
                                positions.update({id(card): card.y + merger.offset for card in cards})
                                current_ids = {id(card) for card in cards}
                                previous_evidence = self._save_scan_evidence(last_page_image) \
                                    if last_page_image is not None and any(id(card) not in current_ids for card, _ in affected) else ''
                                marked = set()
                                for card, note in affected:
                                    if id(card) in marked:
                                        continue
                                    marked.add(id(card))
                                    # 来源采用已核验网格行号，避免合法的像素停位偏移
                                    # 让同一物理卡位在重复扫描时出现不同的位置提示。
                                    origin = origin_y if origin_y is not None else min(item.y for item in cards)
                                    row = round((positions[id(card)] - origin) / (pitch or CARD_GRIDS.delta[1])) + 1
                                    location = f'第 {page + 1} 页发现，累计第 {row} 行第 {card.col + 1} 列'
                                    path = evidence_path if id(card) in current_ids else previous_evidence
                                    evidence = f'；原帧：{path}' if path else ''
                                    card.ship = dict(card.ship, review=True,
                                                     source=f'{location}；{note}，待人工核对{evidence}；{card.ship["source"]}'[:200])
                                    # 未确认名称保留实际 OCR 读数供人工定位；review
                                    # 标记仍使其独立保留，不能作为已确认身份合并或计费。
                                logger.warning(f'[{self.scan_label}] {reason}重读仍未确认：{locations}；已标记待核对，继续扫描')
                            else:
                                logger.warning(f'{reason}未确认，重新截图核对（{read_attempts}/3）：{locations}')
                                previous = None
                                stable.reset()
                                waiting.reset()
                                continue
                        previous_slots = len(merger.slots)
                        merger.add(image, cards)
                        last_page_image = image
                        # 置顶编队读数影响当前边界，保留其原帧和最终卡位数据，
                        # 便于区分编号误读、透明背景与排序冲突；普通正常页不写图。
                        if (diagnostic_pages or any(card.fleet > 0 for card in cards) or evidence_path) and evidence_frame is not image:
                            evidence_path = self._save_scan_evidence(image)
                            evidence_frame = image
                        if evidence_path:
                            try:
                                Path(evidence_path).with_suffix('.json').write_text(json.dumps(
                                    [dict(x=card.x, y=card.y, col=card.col, ship=card.ship,
                                          fleet=card.fleet, level_reliable=card.level_reliable,
                                          name_reads=card.name_reads, name_ellipsis=card.name_ellipsis) for card in cards],
                                    ensure_ascii=False, indent=2), encoding='utf-8')
                            except OSError as exc:
                                logger.warning(f'扫描卡位诊断保存失败：{exc}')
                    except ValueError as exc:
                        raise MindCalculatorScanError(str(exc)) from exc
                    read_attempts = 0
                    evidence_path = ''
                    evidence_frame = None
                    page += 1
                    if len(merger.slots) > previous_slots:
                        # 新页经位移与网格核验后已完成读取；有界 OCR 复读的耗时
                        # 不应占用下一段滚动的期限，重复旧船位仍不能续期。
                        progress.reset()
                    if len(merger.slots) > 5000:
                        raise MindCalculatorScanError('识别卡片超过 5000，请核对船坞布局，保留旧扫描结果')
                    logger.attr('扫描页', page)
                    logger.attr('识别卡片', len(merger.slots))
                    identity_label = '按群组取最高' if getattr(merger, 'group_identity', False) else '同名取最高'
                    logger.attr(f'范围内舰船（{identity_label}）', len(merger.ships(policy.min_level, policy.max_level)))
                    logger.attr('本页等级', ','.join(str(card.ship['level']) for card in cards))
                    logger.attr('本页编队', ','.join(str(card.fleet) for card in cards))
                    logger.attr('本页识别摘要', sha256(json.dumps(
                        [dict(ship=card.ship, fleet=card.fleet, level_reliable=card.level_reliable) for card in cards],
                        ensure_ascii=False, sort_keys=True).encode()).hexdigest())
                    logger.info(f'[{self.scan_label}] 第 {page} 页，已读取 {len(merger.slots)} 格，'
                                f'范围内 {len(merger.ships(policy.min_level, policy.max_level))} 艘（{identity_label}）')
                    if policy.can_stop(cards, merger.slots):
                        self._scan_metadata = dict(reached_bottom=False, physical_count=len(merger.slots))
                        logger.info(f'[{self.scan_label}] 连续三排共 {len(cards)} 艘均低于 {policy.min_level} 级，已核实等级降序，扫描结束')
                        break
                    logger.attr('早停检查', policy.stop_reason(cards, merger.slots))
                    if at_bottom:
                        self._scan_metadata = dict(reached_bottom=True, physical_count=len(merger.slots))
                        cap_note = '，已核实连通圆角端帽' if thumb[-1] < DOCK_SCROLL.total - 2 else ''
                        logger.info(f'[{self.scan_label}] 已确认滚动条底部（严格颜色 {thumb[-1] + 1}/{DOCK_SCROLL.total}px'
                                    f'{cap_note}），扫描结束')
                        break
                    rows = sorted({card.y for card in cards})
                    if len(rows) != 3:
                        raise MindCalculatorScanError('船坞未显示三排完整船名，无法安全按三排推进')
                    if pitch is None:
                        distances = np.diff(rows)
                        pitch = int(round(float(np.median(distances))))
                        origin_y = rows[0]
                        if not 180 <= pitch <= 250 or max(abs(distances - pitch)) > 3:
                            raise MindCalculatorScanError('无法确认船坞实际行距，保留旧扫描结果')
                        motion.row_pitch = pitch
                        logger.attr('船坞行距', f'{pitch}px，三排 {3 * pitch}px')
                    expected_offset = (page - 1) * 3 * pitch
                    if any(abs(y + merger.offset - origin_y - expected_offset - index * pitch) > 6
                           for index, y in enumerate(rows)):
                        raise MindCalculatorScanError('三排位移与卡片行位置不一致，保留旧扫描结果')
                    target = page * 3 * pitch
                    attempts = 0
                    logger.attr('船坞三排目标', f'{target}px')
                    if page >= 500:
                        raise GameStuckError('船坞扫描未能到达底部')
                waiting.reset()
                if drag.reached():
                    if attempts >= 8:
                        raise MindCalculatorScanError('船坞三排定位未能停在目标位置，请检查控制方式')
                    remaining = target - merger.offset
                    last_drag = self._drag_rows(int(np.clip(remaining, -pitch, pitch)))
                    attempts += 1
                    drag.reset()
                    stable.reset()
                    previous = None
                continue
            if self.handle_popup_confirm():
                previous = None
                stable.reset()
                continue
        return merger.ships(policy.min_level, policy.max_level)
