import { BookOpen } from 'lucide-react'
import type { ShopStrategyTask } from '../api/types'
import type { Language } from '../i18n'

interface MethodCopy {
  where: string
  score: string
  orderBy: string
  cap: string
  take: string
}

interface HelpCopy {
  ariaLabel: string
  title: string
  overview: string
  headings: {
    modes: string
    syntax: string
    candidates: string
    context: string
    domains: string
    taskRules: string
    plan: string
  }
  modeItems: readonly string[]
  syntax: string
  candidateIntro: string
  methods: MethodCopy
  table: {object: string; fields: string; description: string; task: string; domain: string; rules: string; currency: string}
  itemIdentity: string
  itemPurchase: string
  contextDomain: string
  contextSession: string
  contextNote: string
  currentDomain: string
  planItems: readonly string[]
}

type LocalizedText = Record<Language, string>

interface DomainInfo {
  domain: string
  description: LocalizedText
  currency: string
  rule: LocalizedText
}

function miaoize(text: string): string {
  return text.endsWith('。') ? `${text.slice(0, -1)}喵。` : `${text}喵`
}

function localized(zhCN: string, enUS: string, jaJP: string, zhTW: string, zhMiao = miaoize(zhCN)): LocalizedText {
  return {'zh-CN': zhCN, 'en-US': enUS, 'ja-JP': jaJP, 'zh-TW': zhTW, 'zh-MIAO': zhMiao}
}

const domainByTask: Record<ShopStrategyTask, DomainInfo> = {
  EventShop: {
    domain: 'event',
    description: localized(
      '活动商店；商品与货币来自当前识别结果。',
      'Event shop; products and currencies come from the current recognition result.',
      'イベントショップ。商品と通貨は現在の認識結果から取得します。',
      '活動商店；商品與貨幣來自目前辨識結果。',
    ),
    currency: 'pt, URpt',
    rule: localized(
      '高级模式只计划普通 PT 候选；旧的 UR 舰、URpt 兑换和未获得物品强制阶段不会执行。需要购买的普通商品必须由脚本明确选入计划。',
      'Advanced mode plans ordinary PT candidates only. The legacy UR ship, URpt exchange, and unobtained-item forced stages do not run. Include every ordinary item you want to buy in the script plan.',
      '高度モードは通常 PT 候補だけを計画します。従来の UR 艦、URpt 交換、未入手アイテムの強制処理は実行されません。購入する通常商品はスクリプト計画に明示的に含めてください。',
      '進階模式只規劃一般 PT 候選；舊有的 UR 艦、URpt 兌換與未取得物品強制階段不會執行。想購買的一般商品必須明確加入指令碼計畫。',
    ),
  },
  ShopFrequent: {
    domain: 'general',
    description: localized(
      '常驻商店；使用当前常驻商店识别出的商品和货币。',
      'Frequent shop; uses products and currencies recognized in the current general shop.',
      '常設ショップ。現在の常設ショップで認識した商品と通貨を使用します。',
      '常駐商店；使用目前常駐商店辨識出的商品與貨幣。',
    ),
    currency: 'Coins, Gems',
    rule: localized(
      '钻石商品仍受“允许使用钻石”开关和真实余额的硬性检查。',
      'Gem products remain subject to the Use Gems option and the actual-balance hard check.',
      'ダイヤ商品は「ダイヤ使用」設定と実残高のハードチェックを引き続き受けます。',
      '鑽石商品仍受「允許使用鑽石」開關與實際餘額的硬性檢查。',
    ),
  },
  ShopOnce: {
    domain: 'general',
    description: localized(
      '一次性常规商店；大舰队、勋章、功勋、核心商店共享此域，可由商品字段区分。',
      'One-time general shops. Guild, medal, merit, and core shops share this domain and can be distinguished by item fields.',
      '単発の通常ショップ。大艦隊、勲章、功勲、コアショップはこのドメインを共有し、商品フィールドで区別できます。',
      '一次性常規商店；大艦隊、勳章、功勳、核心商店共用此域，可由商品欄位區分。',
    ),
    currency: 'GuildCoins, Medal, Merit, Core',
    rule: localized(
      '每个子商店只暴露它当前实际使用的货币键和可购买候选；每个子商店都是独立策略会话，reserve、max_spend 和 cap 不跨子商店累计。',
      'Each sub-shop exposes only the currency keys and purchasable candidates it actually uses. Every sub-shop is an independent strategy session, so reserve, max_spend, and cap do not carry across sub-shops.',
      '各サブショップは、実際に使用する通貨キーと購入可能な候補だけを公開します。各サブショップは独立した戦略セッションであり、reserve、max_spend、cap はサブショップ間で引き継がれません。',
      '每個子商店只會公開它目前實際使用的貨幣鍵與可購買候選；每個子商店都是獨立策略工作階段，reserve、max_spend 與 cap 不會跨子商店累計。',
    ),
  },
  PrivateQuarters: {
    domain: 'private_quarters',
    description: localized(
      '私人休息室商店。',
      'Private Quarters shop.',
      'プライベートクォーターのショップ。',
      '私人休息室商店。',
    ),
    currency: 'Coins, Gems',
    rule: localized(
      '高级模式由脚本选择已识别礼物；旧的购买玫瑰/蛋糕开关只在简单模式生效。',
      'Advanced mode lets the script select recognized gifts; the legacy roses/cake switches apply only in simple mode.',
      '高度モードでは認識済みギフトをスクリプトが選択します。従来のバラ/ケーキ購入設定は簡易モードだけで有効です。',
      '進階模式由指令碼選擇已辨識禮物；舊有的購買玫瑰/蛋糕開關只在簡易模式生效。',
    ),
  },
  OpsiShop: {
    domain: 'opsi',
    description: localized(
      '大世界港口商店。地图事件中的明石商店继续使用现有规则。',
      'Operation Siren port shop. Map-event Akashi shops continue to use their existing rules.',
      'セイレーン作戦の港ショップ。マップイベント中の明石ショップは既存ルールを継続して使用します。',
      '大世界港口商店。地圖事件中的明石商店會繼續使用既有規則。',
    ),
    currency: 'YellowCoins, PurpleCoins',
    rule: localized(
      'CL1、货币保留、库存与港口页面检查始终由 Python 强制执行。',
      'CL1, currency reserves, stock, and port-page checks are always enforced by Python.',
      'CL1、通貨の留保、在庫、港画面のチェックは常に Python が強制します。',
      'CL1、貨幣保留、庫存與港口頁面檢查一律由 Python 強制執行。',
    ),
  },
  OpsiVoucher: {
    domain: 'opsi_voucher',
    description: localized(
      '大世界凭证商店。',
      'Operation Siren voucher shop.',
      'セイレーン作戦のバウチャーショップ。',
      '大世界憑證商店。',
    ),
    currency: 'Voucher',
    rule: localized(
      '游戏内库存和确认弹窗始终是最终数量上限。',
      'In-game stock and the confirmation dialog remain the final quantity limit.',
      'ゲーム内在庫と確認ダイアログが常に最終的な数量上限です。',
      '遊戲內庫存與確認彈窗始終是最終數量上限。',
    ),
  },
}

const syntax = `local pool = candidates
  :where(function(item) return item.available end)

if context.domain == 'event' then
  return shop.plan {
    reserve = { pt = 3000 },
    max_spend = { pt = 5000 },
    candidates = pool:score(function(item) return 1000 - item.price end):take(20)
  }
elseif context.currency['Coins'] > 0 then
  return shop.plan {
    candidates = pool:order_by('price'):take(20)
  }
else
  return shop.plan { candidates = pool:take(0) }
end`

const zhCN: HelpCopy = {
  ariaLabel: '高级商店策略说明',
  title: '高级商店策略说明',
  overview: '简单模式继续使用原有过滤器。高级模式把已识别商品投影为只读候选列表，并要求脚本返回购买计划；脚本不能点击、读写配置、访问设备、网络或文件。',
  headings: {modes: '模式与生效条件', syntax: '受限 Lua 语法', candidates: '候选链', context: '可读取上下文', domains: '任务与上下文域', taskRules: '各任务货币与固定规则', plan: '计划行为与硬性限制'},
  modeItems: [
    '简单模式：沿用每个商店原有的过滤器和购买逻辑。',
    '高级模式：使用本组策略脚本。编辑只保存在浏览器本地草稿；必须先检查通过，再点击“应用”写入配置。',
    '脚本校验失败或运行时无法产出有效计划时，本轮高级购买会安全跳过，不会回退为未检查的脚本。',
  ],
  syntax: '顶层只允许 local 名称 = 表达式或候选链、if / elseif / else ... then ... end，以及 return shop.plan {...}。local 只能在顶层定义一次且不能重新赋值；所有可达分支都必须返回计划。表达式支持 nil、布尔值、数字、字符串、and / or / not、算术 + - * / // % ^ 和比较 == ~= < <= > >=。注释使用 -- 单行或 --[[ 多行 ]]。遵循 Lua 真值：只有 nil 和 false 为假，0 与空字符串仍为真。',
  candidateIntro: '从 candidates 或前一个候选链继续调用。匿名函数只允许作为 where 或 score 的参数，固定形态为 function(item) return 表达式 end。',
  methods: {
    where: '保留返回真值的候选项。',
    score: '为候选项计算有限数值评分。score 会按分数降序，take 先截取前 n 个候选；随后规划器只在这 n 项内，在预算、库存和配额下选择使 sum(评分 × 购买数量) 最大的整数数量组合，而不是只按单次评分排序。必须显式 take，且 n 不得超过 20。',
    orderBy: '按候选字段稳定排序。第二个参数只能是 asc 或 desc；省略方向时默认 asc，值为 nil 的候选始终排在末尾。',
    cap: '字段必须是候选字段，值必须是 Lua 基本字面量；它限制字段值相同候选的累计实际购买数量。用量跨同一商店会话和刷新保存；多个 cap 可叠加，命中时必须同时满足。',
    take: '截取前 n 个候选项，n 为 0 到 100 的整数。使用 score 时 n 最多为 20。',
  },
  table: {object: '对象', fields: '字段', description: '说明', task: '任务', domain: 'context.domain', rules: '规则', currency: '常见 context.currency 键'},
  itemIdentity: '商品身份与分类。',
  itemPurchase: '价格、货币、库存、单商品数量上限和可用状态。',
  contextDomain: '当前任务的固定只读域。',
  contextSession: '当前余额、本会话已消费额和脚本可读取的已购买记录。',
  contextNote: '候选项来自后端完成商品识别后的纯数据投影；脚本不能得到原始商品、设备或配置对象。context.currency 和 context.spent 的方括号访问只能使用固定字符串键，例如 context.currency[\'pt\']。context.purchased 按候选 item.id 记录本会话实际购买量；在 where/score 候选函数中可用 context.purchased[item.id] 查询，未知记录返回 0。库存扣减和 cap 的跨刷新用量由宿主在内部维护。',
  currentDomain: '当前任务使用 {domain} 域。context.domain 由后端固定注入且只读，脚本不能修改。',
  planItems: [
    'shop.plan 只能包含 reserve、max_spend 和必填的单条 candidates 候选链。reserve 与 max_spend 都是 {货币名 = 非负整数} 映射；reserve 是当前余额必须留下的金额，max_spend 是整个本次商店会话的累计消费上限。',
    '候选链总调用数最多 16，不能返回多条候选链。score 只能使用一次，且必须在 take 之前；take 只能使用一次。',
    '源码最长 20,000 个字符，AST 最多 500 个节点。注释会被忽略但仍计入长度；算术结果必须为绝对值不超过 10^12 的有限数值，幂指数绝对值最多 64；评分组合规划最多搜索 50,000 个状态，超过上限会安全拒绝本轮购买。',
    '不支持循环、任意赋值、模块导入、任意函数调用、对象写入、I/O、网络、设备控制或 Python 对象访问。',
    '即使脚本检查通过，实际购买仍由宿主复核余额、保留额、消费上限、库存、数量和游戏界面状态；不满足硬条件的动作会被拒绝或跳过。',
  ],
}

const enUS: HelpCopy = {
  ariaLabel: 'Advanced shop strategy reference',
  title: 'Advanced Shop Strategy Reference',
  overview: 'Simple mode keeps the existing filter. Advanced mode projects recognized products into a read-only candidate list and requires the script to return a purchase plan; the script cannot click, read or write configuration, or access devices, networks, or files.',
  headings: {modes: 'Modes and activation', syntax: 'Restricted Lua syntax', candidates: 'Candidate pipeline', context: 'Readable context', domains: 'Tasks and context domains', taskRules: 'Currencies and task-specific rules', plan: 'Plan behavior and hard limits'},
  modeItems: [
    'Simple mode: uses each shop\'s existing filter and purchase flow.',
    'Advanced mode: uses this group\'s strategy script. Edits stay in a browser-local draft until they pass Check and you select Apply to write configuration.',
    'If validation fails or execution cannot produce a valid plan, this advanced purchase pass safely skips. It never falls back to an unchecked script.',
  ],
  syntax: 'At top level, only local name = expression or candidate pipeline, if / elseif / else ... then ... end, and return shop.plan {...} are allowed. A local may be defined only once at top level and cannot be reassigned; every reachable branch must return a plan. Expressions support nil, booleans, numbers, strings, and / or / not, arithmetic + - * / // % ^, and comparisons == ~= < <= > >=. Use -- for line comments or --[[ ... ]] for block comments. Lua truthiness applies: only nil and false are false; 0 and empty strings are true.',
  candidateIntro: 'Start from candidates or a previous candidate pipeline. Anonymous functions are allowed only as where or score arguments and must be exactly function(item) return expression end.',
  methods: {
    where: 'Keeps candidates whose expression is truthy.',
    score: 'Calculates a finite numeric score. score ranks candidates descending and take first keeps the top n; the planner then chooses, only among those n, the feasible integer quantity combination that maximizes sum(score × quantity) under budget, stock, and cap constraints. It does not merely sort by one score. take is mandatory and n must be at most 20.',
    orderBy: 'Stably sorts by a candidate field. The optional second argument is asc or desc; omitted direction defaults to asc, and candidates whose value is nil always sort last.',
    cap: 'The field must be a candidate field and the value must be a Lua primitive literal. It limits the cumulative actually purchased quantity of candidates with the same field value. Usage persists across one shop session and refreshes; multiple caps all apply.',
    take: 'Keeps the first n candidate entries, where n is an integer from 0 to 100. With score, n is at most 20.',
  },
  table: {object: 'Object', fields: 'Fields', description: 'Description', task: 'Task', domain: 'context.domain', rules: 'Rules', currency: 'Common context.currency keys'},
  itemIdentity: 'Product identity and classification.',
  itemPurchase: 'Price, currency, stock, per-product quantity limit, and availability.',
  contextDomain: 'The fixed read-only domain for the current task.',
  contextSession: 'Current balances, amounts spent in this session, and script-readable purchase records.',
  contextNote: 'Candidates are pure data projected after the backend recognizes products; scripts never receive raw products, devices, or configuration. Bracket access for context.currency and context.spent needs a fixed string key, for example context.currency[\'pt\']. context.purchased records actual session purchases by candidate item.id; inside a where/score candidate function, query it with context.purchased[item.id], and an unknown record returns 0. Stock deduction and cross-refresh cap usage stay internal to the host.',
  currentDomain: 'The current task uses the {domain} domain. The backend injects context.domain as read-only and the script cannot change it.',
  planItems: [
    'shop.plan may contain only reserve, max_spend, and one required candidates pipeline. reserve and max_spend are { currency = non-negative integer } maps; reserve is the amount that must remain from the current balance, while max_spend limits cumulative spending for this shop session.',
    'A candidate pipeline has at most 16 calls and a plan cannot return multiple pipelines. score is allowed once and must precede take; take is allowed once.',
    'Source is limited to 20,000 characters and 500 AST nodes. Comments are ignored but count toward source length. Arithmetic results must be finite with an absolute value no greater than 10^12, and an exponent has an absolute limit of 64. Scored combination planning searches at most 50,000 states, then safely rejects this purchase pass.',
    'Loops, arbitrary assignment, module imports, arbitrary calls, object writes, I/O, network access, device control, and Python object access are unsupported.',
    'Passing Check does not bypass host controls. The host revalidates balances, reserves, spend caps, stock, quantities, and the in-game page state; actions failing a hard condition are rejected or skipped.',
  ],
}

const jaJP: HelpCopy = {
  ariaLabel: '高度ショップ戦略リファレンス',
  title: '高度ショップ戦略リファレンス',
  overview: '簡易モードは既存フィルターを使います。高度モードは認識済み商品を読み取り専用の候補一覧に投影し、スクリプトに購入計画を返させます。スクリプトはクリック、設定の読み書き、端末・ネットワーク・ファイルへのアクセスを行えません。',
  headings: {modes: 'モードと有効条件', syntax: '制限付き Lua 構文', candidates: '候補パイプライン', context: '読み取り可能なコンテキスト', domains: 'タスクとコンテキストドメイン', taskRules: '通貨とタスク固有ルール', plan: '計画の動作とハード制限'},
  modeItems: [
    '簡易モード：各ショップの既存フィルターと購入フローを使用します。',
    '高度モード：このグループの戦略スクリプトを使用します。編集内容はブラウザー内の下書きにだけ保存され、チェック成功後に「適用」を選ぶまで設定へ書き込まれません。',
    '検証失敗、または実行時に有効な計画を作れない場合、この高度購入パスは安全にスキップされます。未検証のスクリプトへフォールバックしません。',
  ],
  syntax: 'トップレベルでは local 名前 = 式または候補パイプライン、if / elseif / else ... then ... end、return shop.plan {...} だけが使えます。local はトップレベルで一度だけ定義でき、再代入できません。到達可能なすべての分岐は計画を返す必要があります。式は nil、真偽値、数値、文字列、and / or / not、算術 + - * / // % ^、比較 == ~= < <= > >= をサポートします。コメントは -- の行コメントまたは --[[ ... ]] のブロックコメントです。Lua の真偽値に従い、偽は nil と false だけで、0 と空文字列は真です。',
  candidateIntro: 'candidates または前の候補パイプラインから続けます。無名関数は where または score の引数にだけ使用でき、形は必ず function(item) return 式 end です。',
  methods: {
    where: '式が真値を返す候補を残します。',
    score: '有限の数値スコアを計算します。score はスコアの降順に並べ、take は先頭 n 件を残します。その n 件だけを対象に、プランナーは予算・在庫・cap の制約内で sum(スコア × 購入数量) を最大にする整数数量の組み合わせを選びます。単純な一回のスコア順ではありません。take は必須で n は 20 以下です。',
    orderBy: '候補フィールドで安定ソートします。第 2 引数は asc または desc です。方向を省略すると asc になり、値が nil の候補は常に末尾になります。',
    cap: 'フィールドは候補フィールド、値は Lua の基本リテラルである必要があります。同じフィールド値を持つ候補の実際に購入した累計数量を制限します。使用量は同一ショップセッションと更新をまたいで保持され、複数の cap はすべて適用されます。',
    take: '先頭から n 件の候補を残します。n は 0 から 100 の整数です。score 使用時は n は 20 以下です。',
  },
  table: {object: 'オブジェクト', fields: 'フィールド', description: '説明', task: 'タスク', domain: 'context.domain', rules: 'ルール', currency: '主な context.currency キー'},
  itemIdentity: '商品の識別と分類。',
  itemPurchase: '価格、通貨、在庫、商品ごとの数量上限、有効状態。',
  contextDomain: '現在のタスクに固定された読み取り専用ドメイン。',
  contextSession: '現在の残高、このセッションの消費額、スクリプトが読める購入記録。',
  contextNote: '候補はバックエンドの商品認識後に投影された純粋なデータです。スクリプトは元の商品、端末、設定オブジェクトを取得できません。context.currency と context.spent の角括弧アクセスには context.currency[\'pt\'] のような固定文字列キーが必要です。context.purchased は候補 item.id ごとの実購入数を記録し、where/score の候補関数内では context.purchased[item.id] で照会できます。存在しない記録は 0 を返します。在庫控除と更新をまたぐ cap 使用量はホスト内部で管理されます。',
  currentDomain: '現在のタスクは {domain} ドメインを使用します。context.domain はバックエンドが読み取り専用で注入し、スクリプトは変更できません。',
  planItems: [
    'shop.plan に含められるのは reserve、max_spend、必須の candidates パイプライン 1 本だけです。reserve と max_spend は { 通貨名 = 非負整数 } のマップです。reserve は現在残高から残す額、max_spend はこのショップセッションの累計消費上限です。',
    '候補パイプラインの呼び出しは最大 16 回で、複数のパイプラインは返せません。score は一度だけ使用でき take より前でなければならず、take も一度だけです。',
    'ソースは 20,000 文字、AST は 500 ノードまでです。コメントは無視されますが長さには含まれます。算術結果は有限で絶対値 10^12 以下、指数の絶対値は 64 以下です。スコア付き組み合わせ計画は最大 50,000 状態を探索し、超えるとこの購入パスを安全に拒否します。',
    'ループ、任意代入、モジュール import、任意呼び出し、オブジェクト書き込み、I/O、ネットワーク、端末制御、Python オブジェクトアクセスはサポートしません。',
    'チェック成功でもホスト制御は回避できません。ホストは残高、留保額、消費上限、在庫、数量、ゲーム画面状態を再検証し、ハード条件を満たさない操作は拒否またはスキップします。',
  ],
}

const zhTW: HelpCopy = {
  ariaLabel: '進階商店策略說明',
  title: '進階商店策略說明',
  overview: '簡易模式繼續使用原有篩選器。進階模式會將已辨識商品投影為唯讀候選清單，並要求指令碼回傳購買計畫；指令碼不能點擊、讀寫設定、存取裝置、網路或檔案。',
  headings: {modes: '模式與生效條件', syntax: '受限 Lua 語法', candidates: '候選鏈', context: '可讀取上下文', domains: '任務與上下文域', taskRules: '各任務貨幣與固定規則', plan: '計畫行為與硬性限制'},
  modeItems: [
    '簡易模式：沿用每個商店原有的篩選器與購買邏輯。',
    '進階模式：使用本組策略指令碼。編輯只保存在瀏覽器本機草稿；必須先檢查通過，再點擊「套用」寫入設定。',
    '指令碼驗證失敗或執行時無法產出有效計畫時，本輪進階購買會安全跳過，不會回退為未檢查的指令碼。',
  ],
  syntax: '頂層只允許 local 名稱 = 表達式或候選鏈、if / elseif / else ... then ... end，以及 return shop.plan {...}。local 只能在頂層定義一次且不能重新賦值；所有可達分支都必須回傳計畫。表達式支援 nil、布林值、數字、字串、and / or / not、算術 + - * / // % ^ 與比較 == ~= < <= > >=。註解使用 -- 單行或 --[[ 多行 ]]。遵循 Lua 真值：只有 nil 與 false 為假，0 與空字串仍為真。',
  candidateIntro: '從 candidates 或前一個候選鏈繼續呼叫。匿名函式只允許作為 where 或 score 的參數，固定形式為 function(item) return 表達式 end。',
  methods: {
    where: '保留回傳真值的候選項。',
    score: '為候選項計算有限數值分數。score 會依分數降序排列，take 先截取前 n 個候選；之後規劃器只在這 n 項內，在預算、庫存與配額限制下選擇使 sum(分數 × 購買數量) 最大的整數數量組合，而不是只依單次分數排序。必須明確使用 take，且 n 不得超過 20。',
    orderBy: '依候選欄位穩定排序。第二個參數只能是 asc 或 desc；省略方向時預設 asc，值為 nil 的候選一律排在最後。',
    cap: '欄位必須是候選欄位，值必須是 Lua 基本常值；它限制欄位值相同候選的累計實際購買數量。用量會跨同一商店工作階段與重新整理保存；多個 cap 可以疊加，命中時必須同時滿足。',
    take: '取前 n 個候選項，n 為 0 到 100 的整數。使用 score 時 n 最多為 20。',
  },
  table: {object: '物件', fields: '欄位', description: '說明', task: '任務', domain: 'context.domain', rules: '規則', currency: '常見 context.currency 鍵'},
  itemIdentity: '商品身分與分類。',
  itemPurchase: '價格、貨幣、庫存、單商品數量上限與可用狀態。',
  contextDomain: '目前任務的固定唯讀域。',
  contextSession: '目前餘額、本工作階段已消費額與指令碼可讀取的已購買記錄。',
  contextNote: '候選項來自後端完成商品辨識後的純資料投影；指令碼不能取得原始商品、裝置或設定物件。context.currency 與 context.spent 的方括號存取只能使用固定字串鍵，例如 context.currency[\'pt\']。context.purchased 依候選 item.id 記錄本工作階段實際購買量；在 where/score 候選函式中可用 context.purchased[item.id] 查詢，未知記錄會回傳 0。庫存扣減與 cap 的跨重新整理用量由宿主在內部維護。',
  currentDomain: '目前任務使用 {domain} 域。context.domain 由後端固定注入且唯讀，指令碼不能修改。',
  planItems: [
    'shop.plan 只能包含 reserve、max_spend 與必填的單條 candidates 候選鏈。reserve 與 max_spend 都是 { 貨幣名 = 非負整數 } 映射；reserve 是目前餘額必須留下的金額，max_spend 是整個本次商店工作階段的累計消費上限。',
    '候選鏈總呼叫數最多 16，不能回傳多條候選鏈。score 只能使用一次且必須在 take 之前；take 只能使用一次。',
    '原始碼最長 20,000 個字元，AST 最多 500 個節點。註解會被忽略但仍計入長度；算術結果必須是絕對值不超過 10^12 的有限數值，冪指數絕對值最多 64；評分組合規劃最多搜尋 50,000 個狀態，超過上限會安全拒絕本輪購買。',
    '不支援迴圈、任意賦值、模組匯入、任意函式呼叫、物件寫入、I/O、網路、裝置控制或 Python 物件存取。',
    '即使指令碼檢查通過，實際購買仍會由宿主複核餘額、保留額、消費上限、庫存、數量與遊戲頁面狀態；不符合硬條件的動作會被拒絕或跳過。',
  ],
}

const zhMiao: HelpCopy = {
  ...zhCN,
  ariaLabel: miaoize(zhCN.ariaLabel),
  title: miaoize(zhCN.title),
  overview: miaoize(zhCN.overview),
  headings: {
    modes: miaoize(zhCN.headings.modes),
    syntax: miaoize(zhCN.headings.syntax),
    candidates: miaoize(zhCN.headings.candidates),
    context: miaoize(zhCN.headings.context),
    domains: miaoize(zhCN.headings.domains),
    taskRules: miaoize(zhCN.headings.taskRules),
    plan: miaoize(zhCN.headings.plan),
  },
  modeItems: zhCN.modeItems.map(miaoize),
  syntax: miaoize(zhCN.syntax),
  candidateIntro: miaoize(zhCN.candidateIntro),
  methods: {
    where: miaoize(zhCN.methods.where),
    score: miaoize(zhCN.methods.score),
    orderBy: miaoize(zhCN.methods.orderBy),
    cap: miaoize(zhCN.methods.cap),
    take: miaoize(zhCN.methods.take),
  },
  table: {
    object: miaoize(zhCN.table.object),
    fields: miaoize(zhCN.table.fields),
    description: miaoize(zhCN.table.description),
    task: miaoize(zhCN.table.task),
    domain: zhCN.table.domain,
    rules: miaoize(zhCN.table.rules),
    currency: miaoize(zhCN.table.currency),
  },
  itemIdentity: miaoize(zhCN.itemIdentity),
  itemPurchase: miaoize(zhCN.itemPurchase),
  contextDomain: miaoize(zhCN.contextDomain),
  contextSession: miaoize(zhCN.contextSession),
  contextNote: miaoize(zhCN.contextNote),
  currentDomain: miaoize(zhCN.currentDomain),
  planItems: zhCN.planItems.map(miaoize),
}

const copyByLanguage: Record<Language, HelpCopy> = {
  'zh-CN': zhCN,
  'en-US': enUS,
  'ja-JP': jaJP,
  'zh-TW': zhTW,
  'zh-MIAO': zhMiao,
}

function interpolate(template: string, domain: string): string {
  return template.replace('{domain}', domain)
}

export function ShopStrategyHelp({task, language = 'zh-CN'}: {task: string; language?: Language}) {
  const copy = copyByLanguage[language]
  const current = domainByTask[task as ShopStrategyTask]
  return <section className="shop-strategy-help" aria-label={copy.ariaLabel}>
    <details open>
      <summary><BookOpen size={17} aria-hidden="true"/><span>{copy.title}</span></summary>
      <div className="shop-strategy-help-body">
        <p>{copy.overview}</p>

        <h3>{copy.headings.modes}</h3>
        <ul>{copy.modeItems.map(item => <li key={item}>{item}</li>)}</ul>

        <h3>{copy.headings.syntax}</h3>
        <p>{copy.syntax}</p>
        <pre><code>{syntax}</code></pre>

        <h3>{copy.headings.candidates}</h3>
        <p>{copy.candidateIntro}</p>
        <dl className="shop-strategy-api">
          <div><dt><code>:where(function(item) return expression end)</code></dt><dd>{copy.methods.where}</dd></div>
          <div><dt><code>:score(function(item) return expression end)</code></dt><dd>{copy.methods.score}</dd></div>
          <div><dt><code>:order_by('field' [, 'asc' | 'desc'])</code></dt><dd>{copy.methods.orderBy}</dd></div>
          <div><dt><code>:cap('field', value, non-negative-integer)</code></dt><dd>{copy.methods.cap}</dd></div>
          <div><dt><code>:take(n)</code></dt><dd>{copy.methods.take}</dd></div>
        </dl>

        <h3>{copy.headings.context}</h3>
        <div className="shop-strategy-table-wrap"><table>
          <thead><tr><th>{copy.table.object}</th><th>{copy.table.fields}</th><th>{copy.table.description}</th></tr></thead>
          <tbody>
            <tr><td><code>item</code></td><td><code>id, key, name, group, sub_genre, tier</code></td><td>{copy.itemIdentity}</td></tr>
            <tr><td><code>item</code></td><td><code>price, cost, stock, max_quantity, available</code></td><td>{copy.itemPurchase}</td></tr>
            <tr><td><code>context</code></td><td><code>domain</code></td><td>{copy.contextDomain}</td></tr>
            <tr><td><code>context</code></td><td><code>currency, spent, purchased</code></td><td>{copy.contextSession}</td></tr>
          </tbody>
        </table></div>
        <p>{copy.contextNote}</p>

        <h3>{copy.headings.domains}</h3>
        <div className="shop-strategy-table-wrap"><table>
          <thead><tr><th>{copy.table.task}</th><th>{copy.table.domain}</th><th>{copy.table.description}</th></tr></thead>
          <tbody>{(Object.entries(domainByTask) as Array<[ShopStrategyTask, DomainInfo]>).map(([name, entry]) => <tr key={name} className={name === task ? 'is-current' : ''}><td><code>{name}</code></td><td><code>{entry.domain}</code></td><td>{entry.description[language]}</td></tr>)}</tbody>
        </table></div>
        {current && <p className="shop-strategy-current">{interpolate(copy.currentDomain, current.domain)}</p>}

        <h3>{copy.headings.taskRules}</h3>
        <div className="shop-strategy-table-wrap"><table>
          <thead><tr><th>{copy.table.task}</th><th>{copy.table.currency}</th><th>{copy.table.rules}</th></tr></thead>
          <tbody>{(Object.entries(domainByTask) as Array<[ShopStrategyTask, DomainInfo]>).map(([name, entry]) => <tr key={name} className={name === task ? 'is-current' : ''}><td><code>{name}</code></td><td><code>{entry.currency}</code></td><td>{entry.rule[language]}</td></tr>)}</tbody>
        </table></div>

        <h3>{copy.headings.plan}</h3>
        <ul>{copy.planItems.map(item => <li key={item}>{item}</li>)}</ul>
      </div>
    </details>
  </section>
}
