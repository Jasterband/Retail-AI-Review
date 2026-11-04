# AI 审核规则矩阵

默认阈值（可被请求 `options` 覆盖）：

| 参数 | 默认值 |
|------|--------|
| clarity_threshold | 0.60 |
| human_confidence_threshold | 0.75 |
| watermark_time_skew_minutes | 120 |
| name_match_mode | fuzzy |
| template_similarity_pass | ≥ 0.85 → PASS |
| template_similarity_uncertain | 0.65 ~ 0.85 → UNCERTAIN |
| template_similarity_fail | < 0.65 → FAIL |
| topic_match_mode | exact（归一化后逐字；PPT「字一模一样」） |
| panorama 人数容差 | 计数 confidence < 0.7 → UNCERTAIN |
| image_phash_max_distance | 默认 10（≤ 则判 similar 重复） |
| image_similarity_threshold | 默认 0.92（embedding 余弦 ≥ 则判 similar 重复） |

**UNCERTAIN 策略：** 该规则 `trigger_human=true`；若无硬 FAIL，总状态 `NEED_HUMAN`。

**清晰度门闩：** 材料 `clarity_score < clarity_threshold` → 依赖该图的文本/模版类规则优先 `UNCERTAIN`（人数检测若仍高置信可继续）。

---

## 通用规则（LECTURE_HALL + MICRO）

| rule_code | 输入材料 | 判定 / 阈值 | FAIL | UNCERTAIN→人工 | SKIP 条件 |
|-----------|----------|-------------|------|----------------|-----------|
| ASSET_MISSING | 全部 assets | S3 可读且非空 | 任一必传读失败且不可替代 | — | — |
| ASSET_TYPE_CHECK | 全部照片 + 声明 type | detected_type 与 asset_type 一致；讲者照可抽姓名 | 明显类别错误 | 类别置信度 < human_confidence_threshold | PDF 签到可放宽视觉分类 |
| CLARITY | 全部图 | clarity ≥ clarity_threshold | —（单独一般不 FAIL） | 模糊且该图承载关键规则 | PDF 页面渲染失败走 ERROR/UNCERTAIN |
| KEY_FIELD_MATCH | 海报/展架/讲者照/全景/签到 + form | 抽取 date/time/location/speaker_names 与 form 交叉比对；地点比 `location`；姓名按 name_match_mode | 高置信且不一致 | OCR conf 低或字段缺失 | 无对应材料 |
| TIME_CONSISTENCY | 含时间的照片（水印/海报） | 各图时间落在会议时段 ± skew；大讲堂强调场内时间一致 | 高置信跨日/明显偏离 | 部分图无时间可抽 | 无时间信息则 SKIP |
| BAYER_LOGO | 大讲堂：POSTER+STAND；微型：E_POSTER + PROJECT_INTRO_DISPLAY（及展示图中 PPT） | 检出拜耳 Logo（与 logo_ref 匹配） | 应检材料均未检出 | 检出 conf 灰区 | 材料缺失时由 ASSET_MISSING 覆盖 |
| PANORAMA_COUNT | PANORAMA（可多张合计） | 大讲堂 ≥35；微型 SINGLE≥6、DUAL≥12 | 高置信低于阈值 | 计数 conf < 0.7 | 无全景 |
| SIGNIN_DURATION | SIGNIN | OCR 起止算时长：大讲堂 >120；微型 SINGLE>30、DUAL>60 | 高置信不足 | 模糊/手写难读 | 无签到 |
| IMAGE_DUP | **本场全部照片** pHash/embedding vs **其他会议** `image_dup_history` | **跨会议不得盗用/混用现场照**；近似相似也算。**不查会内**相似图 | 命中其他 meeting | 指纹算不出 → UNCERTAIN | 库空（首场）或无图可读 |
| TOPIC_REUSE | **仅讲者 SPEAKER_PHOTO**（优先 TITLE_GROUP）OCR 标题 + form.topic + topic_history | 同期内主题/标题归一化后不得与他场重复（范围见 refs） | 讲者照标题命中历史 | OCR 标题不清 | 库空，或无标题合影/抽不出标题 |
| WATERMARK_CONSISTENCY | 含水印的图 | 水印日期≈meeting_date；地点文本与 location / chain_or_store_name 模糊匹配；时间在时段±skew | 高置信日期错误 | 无水印或 OCR 差 → 有水印期望时 UNCERTAIN，无水印则 SKIP | 无水印 |

---

## 药师大讲堂专用

| rule_code | 输入材料 | 判定 / 阈值 | FAIL | UNCERTAIN→人工 | 备注 |
|-----------|----------|-------------|------|----------------|------|
| NAME_CARD_SPEAKER_MATCH | NAME_CARD + speakers | OCR 姓名集合 == 讲者姓名集合（通常 4）；先检测多台卡 ROI 再 OCR | 缺人/多人/姓名不符（高置信） | ROI 不全或 OCR 灰区 | evidence 含 names_ocr / missing / extra |
| NAME_CARD_TEMPLATE | NAME_CARD + template NAME_CARD | 底纹/版式相似度 ≥0.85 | <0.65 | 0.65~0.85 | 可选加强项 |
| HANDBOOK_DETECT | HANDBOOK | 识别为「2026菁英药师大讲堂健康教育宣传手册」（封面标题/版式） | 非手册或标题不符 | 遮挡/角度差 | 本地样例常缺独立手册图，黄金集需补 |
| HANDBOOK_NOT_STALE | HANDBOOK + 当期封面 ref | 与当期 template 匹配；旧版封面特征命中则 FAIL | 匹配旧版 ref | 新旧相似度接近 | 「旧版」=旧封面模版，与主题查重无关 |
| SPEAKER_TOPIC_OCR | SPEAKER_PHOTO(TITLE_GROUP) + speaker.topic | 课件标题 vs topic；exact 或归一化（去空格/标点） | 高置信不一致 | OCR 差 | 大讲堂每位讲者 |
| SPEAKER_SHOT_PAIR | 每 speaker 的 SPEAKER_PHOTO | 每位需 TITLE_GROUP + LECTURING 各 ≥1 | 缺一类 | 类型检测不清 | PE 提交前也应校验 |

**大讲堂人数口径：** PPT 业务表单 ≥39 由 PE 校验；AI 全景阈值为 **≥35**（与审核规则表一致）。

---

## 微型药师专用

| rule_code | 输入材料 | 判定 / 阈值 | FAIL | UNCERTAIN→人工 | 备注 |
|-----------|----------|-------------|------|----------------|------|
| PPT_TEMPLATE_MATCH | 权益一 `PROJECT_INTRO_DISPLAY`、权益二 `E_POSTER_DISPLAY` | **权益一**：模版有彩色丝带/波浪装饰；**权益二**：模版有日程表 | 对应特征高置信缺失 | 模糊/透视导致看不清 | 无展示材料 |
| PPT_PAGE_KIND | 同上 | 一张项目介绍（权益一）+ 一张日程（权益二）；不得两张同类 | 页类错误或重复 | 特征识别不清 | |
| SIGNIN_RATIO_AND_STORES | SIGNIN + speakers 数 | 听众数 ≥ 讲者数×6；听众门店种类 ≥2 | 高置信不满足 | 手写门店难识别 | 与 PE 表单人数校验互补 |

**微型讲者照：** 单讲者 1 张标题合影；双讲者各 1 张。无强制 LECTURING 对（与大讲堂不同）。

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
| ASSET_TYPE_CHECK | ✓ | ✓ |
| CLARITY | ✓ | ✓ |
| KEY_FIELD_MATCH | ✓ | ✓ |
| TIME_CONSISTENCY | ✓ | ✓（弱） |
| BAYER_LOGO | ✓ | ✓ |
| PANORAMA_COUNT | ✓ | ✓ |
| SIGNIN_DURATION | ✓ | ✓ |
| IMAGE_DUP | ✓ | ✓ |
| TOPIC_REUSE | ✓（大讲堂必做） | ✓（若有标题合影则做） |
| WATERMARK_CONSISTENCY | ✓ | ✓ |
| NAME_CARD_SPEAKER_MATCH | ✓ | SKIP |
| NAME_CARD_TEMPLATE | ✓ | SKIP |
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
- `BAYER_LOGO`：海报与展架（或微型权益页）检出拜耳 Logo
- `PANORAMA_COUNT`：全景合计 N 人，满足阈值
- `HANDBOOK_DETECT`：识别到当期宣传手册
- `PPT_TEMPLATE_MATCH`：现场公示 PPT 与规定模版一致
- `IMAGE_DUP`：全部照片未盗用其他会议现场照（pHash/embedding；不查会内）
- `TOPIC_REUSE`：讲者照 OCR 标题未与历史主题字符串重复

不合格时 `summary_failed` 使用 `reason_text` 聚合，避免只给「不通过」。
