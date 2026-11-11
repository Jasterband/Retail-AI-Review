# AI 审核规则矩阵

默认阈值（可被请求 `options` 覆盖）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| human_confidence_threshold | 0.75 | |
| watermark_time_skew_minutes | 120 | 仅海报等日程起止时间容差；不做时间水印检测 |
| name_match_mode | fuzzy | |
| template_similarity_pass | ≥ 0.85 → PASS | |
| template_similarity_uncertain | 0.65 ~ 0.85 → UNCERTAIN | |
| template_similarity_fail | < 0.65 → FAIL | |
| topic_match_mode | exact（归一化后逐字；PPT「字一模一样」） | |
| panorama 人数容差 | 计数 confidence < 0.7 → UNCERTAIN | |
| image_phash_max_distance | 默认 10（≤ 则判 similar 重复） | |
| image_similarity_threshold | 默认 0.92（embedding 余弦 ≥ 则判 similar 重复） | |

**UNCERTAIN 策略：** 该规则 `trigger_human=true`；若无硬 FAIL，总状态 `NEED_HUMAN`。

---

## 通用规则（LECTURE_HALL + MICRO）

| rule_code | 输入材料 | 判定 / 阈值 | FAIL | UNCERTAIN→人工 | SKIP 条件 |
|-----------|----------|-------------|------|----------------|-----------|
| ASSET_MISSING | 全部 photos | S3 可读且非空 | 任一必传读失败且不可替代 | — | — |
| KEY_FIELD_MATCH | 海报/展架/讲者照/签到 + form | 日期→`DATE_MISMATCH`；地点→`LOCATION_MISMATCH`；讲者姓名→`SPEAKER_NAME_MISMATCH`（时间另见 TIME_CONSISTENCY→`TIME_MISMATCH`） | 高置信不一致 | OCR conf 低 | 无对应材料 |
| TIME_CONSISTENCY | 海报/展架/电子日程等 | 画面上的日程起止时间落在会议时段 ± skew；**不读时间水印** | 高置信明显偏离 | 部分图无日程时间可抽 | 无日程时间则 SKIP |
| BAYER_LOGO | 大讲堂：EDM+Poster+Stand；微型：EDM+EDMDisplay+ProjectIntro | **微型**：检出拜耳十字 Logo（可与 logo_ref 匹配）；**大讲堂**：图片**最下方**页脚检出赞助方全称「拜耳医药保健有限公司」（不要求 Logo） | 应检材料均未检出 | 检出 conf 灰区 | 材料缺失时由 ASSET_MISSING 覆盖 |
| PANORAMA_COUNT | Panorama（可多张合计） | 大讲堂 ≥35；微型 SINGLE≥6、DUAL≥12 | 高置信低于阈值 | 计数 conf < 0.7 | 无全景 |
| SIGNIN_DURATION | SignSheet（多页合并） | 多张签到表合并后取可读最大时长：大讲堂 >120；微型 SINGLE>30、DUAL>60；**不检签到表模版** | 时长不足 | 读不出起止时间 | 无签到 |
| SIGNIN_COMPLETE | SignSheet（每张独立） | 表头（若有）+ 已占用行除「其他」列外均须填齐 | 任一张缺项 | OCR 灰区 | 无签到 |
| SIGNIN_AUDIENCE | SignSheet（多页合计） | 听众人数达标（大讲堂≥35；微型≥讲者×6） | 高置信低于阈值 | 人数读不出 | 无签到 |
| IMAGE_DUP | 本场图 vs **其他会议**库（1×全库同组）；**有人物**（讲者/授课/全景）↔有人物；**无人物**（手册/海报/展架等）↔无人物 | 跨会不得盗用。有人物+手册：pHash/embedding 近似；**海报/电子海报/展架仅完全一致**（pHash=0）。**不查会内** | 命中其他 meeting | 指纹算不出 → 跳过该张 | 库空（首场）或无同组历史 |
| SPEAKER_COMPOSITION | SpeakerTitle / SpeakerLecture | **标题合影**须同时有讲者、标题、讲者姓名、日期；**授课照**须同时有讲者与 PPT/投影 | 缺要素 → `COMPOSITION_MISSING` | 识别不清 | 无讲者照 |

---

## 药师大讲堂专用

| rule_code | 输入材料 | 判定 / 阈值 | FAIL | UNCERTAIN→人工 | 备注 |
|-----------|----------|-------------|------|----------------|------|
| NAME_CARD_SPEAKER_MATCH | TableCard + speakers | 整图 OCR 姓名集合 == 讲者姓名集合（通常 4）；**不裁框** | 缺人/多人/姓名不符（高置信） | OCR 灰区 / 未抽出 | evidence 含 names_ocr / missing / extra |
| HANDBOOK_DETECT | Manual | 识别为「2026菁英药师大讲堂健康教育宣传手册」（封面标题/版式） | 非手册或标题不符 | 遮挡/角度差 | 本地样例常缺独立手册图，黄金集需补 |
| HANDBOOK_NOT_STALE | Manual + 当期封面 ref | 与当期 template 匹配；旧版封面特征命中则 FAIL | 匹配旧版 ref | 新旧相似度接近 | 「旧版」=旧封面模版，与主题查重无关 |
| SPEAKER_TOPIC_OCR | SpeakerTitle + speaker.topic | 课件标题 vs topic；exact 或归一化（去空格/标点） | 高置信不一致 | OCR 差 | 大讲堂每位讲者 |
| SPEAKER_SHOT_PAIR | 每 speaker 的讲者照 | 每位需 SpeakerTitle + SpeakerLecture 各 ≥1 | 缺一类 | 类型检测不清 | PE 提交前也应校验 |

**大讲堂人数口径：** PPT 业务表单 ≥39 由 PE 校验；AI 全景阈值为 **≥35**（与审核规则表一致）。

---

## 微型药师专用

| rule_code | 输入材料 | 判定 / 阈值 | FAIL | UNCERTAIN→人工 | 备注 |
|-----------|----------|-------------|------|----------------|------|
| PPT_TEMPLATE_MATCH | 权益一 `ProjectIntro`、权益二 `EDMDisplay` | **权益一**：模版有彩色丝带/波浪装饰；**权益二**：模版有日程表 | 对应特征高置信缺失 | 模糊/透视导致看不清 | 无展示材料 |
| PPT_PAGE_KIND | 同上 | 一张项目介绍（权益一）+ 一张日程（权益二）；不得两张同类 | 页类错误/重复 → `TEMPLATE_MISMATCH` | 识别不清 → `TEMPLATE_UNCERTAIN` | |
| SIGNIN_RATIO_AND_STORES | SignSheet（多页合计） | 门店种类并集 ≥2（人数改由 SIGNIN_AUDIENCE） | 门店种类不足 | 手写门店难识别 | 与 SIGNIN_AUDIENCE 互补 |

**微型讲者照：** 单讲者 1 张 `SpeakerTitle`；双讲者各 1 张。无强制 `SpeakerLecture`（与大讲堂不同）。

---

## 不由 AI 执行（PE 系统）

| 规则 | 说明 |
|------|------|
| 同月讲者仅 1 次（大讲堂） | 表单库查询 |
| 同期讲者 ≤3 次（大讲堂） | 表单库查询 |
| 同期主题不重复（大讲堂，同名不考虑） | 表单库查询 |
| 微型同期讲者仅 1 次 | 表单库查询 |
| 表单会议时长 | 大讲堂 >120；微型 ≥讲者数×30 |
| 总参会人数 ≥39（大讲堂表单） | PE |
| （总参会-讲者）/讲者 ≥6（微型表单） | PE |
| 同一听众同专题仅一次 | PE 与 AI 均无法可靠实现 |

---

## 按 project_type 启用矩阵

| rule_code | LECTURE_HALL | MICRO |
|-----------|:------------:|:-----:|
| ASSET_MISSING | ✓ | ✓ |
| KEY_FIELD_MATCH | ✓ | ✓ |
| TIME_CONSISTENCY | ✓ | ✓（弱） |
| BAYER_LOGO | ✓ | ✓ |
| PANORAMA_COUNT | ✓ | ✓ |
| SIGNIN_DURATION | ✓ | ✓ |
| SIGNIN_COMPLETE | ✓ | ✓ |
| SIGNIN_AUDIENCE | ✓ | ✓ |
| IMAGE_DUP | ✓ | ✓ |
| SPEAKER_COMPOSITION | ✓ | ✓（仅 SpeakerTitle 四要素；无授课照） |
| NAME_CARD_SPEAKER_MATCH | ✓ | SKIP |
| HANDBOOK_DETECT | ✓ | SKIP |
| HANDBOOK_NOT_STALE | ✓ | SKIP |
| SPEAKER_TOPIC_OCR | ✓ | SKIP（微型主题比对可选二期） |
| SPEAKER_SHOT_PAIR | ✓ | SKIP |
| PPT_TEMPLATE_MATCH | SKIP | ✓ |
| PPT_PAGE_KIND | SKIP | ✓ |
| SIGNIN_RATIO_AND_STORES | SKIP | ✓ |

---

## 合格输出文案要点（summary_matched）

通过时建议按规则生成可读句，例如：

- `KEY_FIELD_MATCH`：海报/展架日期时间地点与表单一致
- `NAME_CARD_SPEAKER_MATCH`：台卡姓名与系统讲者一致（列出姓名）
- `BAYER_LOGO`：大讲堂海报/展架/电子日程检出赞助方「拜耳医药保健有限公司」；微型电子日程/展示/项目介绍检出拜耳 Logo
- `PANORAMA_COUNT`：全景合计 N 人，满足阈值
- `HANDBOOK_DETECT`：识别到当期宣传手册
- `PPT_TEMPLATE_MATCH`：现场公示 PPT 与规定模版一致
- `IMAGE_DUP`：同组材料未盗用其他会议（有人/无人分组；海报类仅完全一致；不查会内）
- `SPEAKER_COMPOSITION`：标题合影含讲者/标题/姓名/日期；授课照含讲者与 PPT

不合格时 `summary_failed` 使用 `reason_text` 聚合，避免只给「不通过」。
