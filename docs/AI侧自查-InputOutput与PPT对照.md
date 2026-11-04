# AI 侧自查：Input / Output 与 PPT 对照

> **给自己看的笔记**，不是发给 PE 的接口文档。  
> 正式对接仍以 [PE接口文档-v1.8.md](PE接口文档-v1.8.md) 为准。  
> PPT：`bayer零售pharmacy engagement方案20261019.pptx`

**你怎么记：**

- **Input** = PE 一次提交整场会（表单 + 所有照片 S3 地址）  
- **Output** = 一次返回总状态 + 多条 `rule_results`（不是每个检查项一个接口）  
- PPT 12–14 页的 AI 规则 → 落在 Output 的 `rule_code` 里  

---

## 0. 和对外文档的关系

| 文档 | 给谁 | 内容 |
|------|------|------|
| [PE接口文档-v1.8.md](PE接口文档-v1.8.md) | PE | 怎么调 API、字段格式 |
| [03-rule-matrix.md](03-rule-matrix.md) | 自己实现 | 每条规则怎么判 |
| [04-template-pack.md](04-template-pack.md) | 自己实现 | 模版 crop |
| **本文** | **自己** | Input/Output 每项对应 PPT 哪一页 |

---

## 1. INPUT（`POST /v1/retail_meeting_checks` 请求体）

### 1.1 顶层 / 会议是谁

| 接口字段 | 含义 | PPT 对应 |
|----------|------|----------|
| `request_id` | 本次审核流水号（幂等） | PPT 无；对接需要。第 5 页「提交后推 AI」 |
| `meeting_id` | PE 会议主键 | PPT 未写库 ID；对应第 5 页会议记录 |
| `session_no` | 场次编号 | 第 5、6、7、9 页 |
| `project_type` | `LECTURE_HALL` / `MICRO` | 第 4、7、9 页项目类型；第 12 / 13 分册规则 |
| `meeting_subtype` | 微型：`SINGLE`/`DUAL`；大讲堂 `null` | 第 9 页会议类型；第 6 页：大讲堂可空 |
| `period_id` | 项目期数 | 第 4 页期数；第 7、9 页选「项目类型名称」 |

### 1.2 `form` 表单（标准答案，拿来和照片比对）

| 接口字段 | 含义 | PPT 对应 |
|----------|------|----------|
| `meeting_name` | 会议名称 | 第 5、6、7、9 页 |
| `meeting_date` | 日期 | 第 5、6、7、9 页 |
| `start_time` / `end_time` | 起止时间 | 第 6、7、9 页 |
| `chain_or_store_name` | 连锁名或药店名 | 第 5、6 页；第 7 连锁；第 9 药店 |
| `location` | **会议地点**（比对海报/水印用这个） | 第 5、6、7、9 页；第 12、13「地点一致」 |
| `remark` | 备注 | 第 5–9 页（可空） |
| `total_attendees` | 总参会人数 | 第 5–9 页；人数硬阈值多在 PE，你主要看全景图 |

### 1.3 `form.speakers[]`

| 接口字段 | 含义 | PPT 对应 |
|----------|------|----------|
| `speaker_id` | 讲者 ID | PPT 无；实现需要 |
| `role_title` | 身份 | 第 6、7、9 页「讲者-身份」 |
| `store_name` | 所属门店 | 第 6、7、9 页 |
| `speaker_name` | 姓名 | 第 6、7、9 页；第 12 台卡四名 / 关键信息一致 |
| `topic` | 讲题 | 第 6、7、9 页；第 12、14 与课件标题比对 |
| `service_minutes` | 服务时长 | 第 6、7、9 页 |
| `fee` / `tax` | 讲课费 / 税金 | 第 6、7、9 页（一般不审钱） |

### 1.4 `assets[]`（照片 type + S3）

PPT 第 12 页：「系统会给出，输入时设计 type」→ 就是 `asset_type`。  
**只传 `s3_uri`，不传文件本身。**

#### 大讲堂（PPT 第 7、12 页）

| asset_type | PPT 叫法 | PPT | 备注 |
|------------|----------|-----|------|
| `E_POSTER` | 电子日程海报 | 7 | |
| `POSTER` | 日程海报 | 7、12 | |
| `STAND` | 日程展架 | 7、12 | |
| `NAME_CARD` | 台卡 | 7、12 | **你后补：姓名 vs 系统讲者** |
| `HANDBOOK` | 手册 | 7、12 | **你后补：宣传手册识别 + 旧版** |
| `SPEAKER_PHOTO` + `TITLE_GROUP`/`LECTURING` | 每讲者 2 张 | 7、12 | |
| `PANORAMA` | 全景 ≥1 | 7、12 | |
| `SIGNIN` | 签到表 ≥1 | 7、12 | 可 jpg/pdf |

#### 微型（PPT 第 9、13 页）

| asset_type | PPT 叫法 | PPT | 备注 |
|------------|----------|-----|------|
| `E_POSTER` | 电子日程海报 | 9、13 | |
| `E_POSTER_DISPLAY` | 电子日程海报展示 | 9、13 | **你后补：PPT 模版匹配** |
| `PROJECT_INTRO_DISPLAY` | 项目介绍展示 | 9、13 | **你后补：PPT 模版匹配** |
| `SPEAKER_PHOTO` | 单 1 / 双 2 标题合影 | 9、13 | |
| `PANORAMA` | 全景 | 9、13 | |
| `SIGNIN` | 签到表 | 9、13 | |

每条还带：`asset_id`、`s3_uri`、`content_type`；（讲者照）`speaker_id`、`speaker_shot_kind`。

### 1.5 可选 `refs` / `options`

| 字段 | 用途 | PPT |
|------|------|-----|
| `refs.template_pack_version` | 用哪版模版包（crop） | PPT 无明文；支撑第 13 页权益 PPT + 你后补模版 |
| `refs.logo_ref_s3` | Logo 参考图 | 第 12、13、14 拜耳 Logo |
| `refs.topic_search_scope` | 主题查重范围 period/all（仅讲者照标题） | 第 12、14「主题不得重复」；图片相似另见 IMAGE_DUP |
| `options.clarity_threshold` 等 | 清晰度/人工阈值 | 第 12–14「看清晰程度，不一定」 |

---

## 2. OUTPUT（查询 / 回调终态）

**两种模式：** `simple`（默认，给 PE）看「哪张不合格 + 原因」；`full`（给 AI）带 checks/OCR/evidence。见接口文档 §4.2。

### 2.1 总结果 ↔ PPT 第 5、14 页

| 接口字段 | 含义 | PPT |
|----------|------|-----|
| `response_mode` | `simple` \| `full` | 对接约定 |
| `request_id` / `job_id` / `attempt_no` | 哪次任务 | 第 5 页 AI 校验次数（次数由 PE +1） |
| `overall_status=PASS` | 通过 | 第 5 页「通过」 |
| `overall_status=FAIL` | 不通过 | 第 5 页「不通过」 |
| `overall_status=NEED_HUMAN` | 待人工 | PPT 未单列；对应「清晰度不够判不准」 |
| `overall_status=ERROR` | 系统错（如下载失败） | PPT 无；对接扩展；**别当业务 FAIL** |
| `summary_matched` | 对上了哪些 | 第 14 页输出要可展示 |
| `summary_failed` | 为啥不过 | 第 14 页「不通过原因」 |
| `need_human_reasons` | 为啥人工 | 清晰度不确定场景 |
| `error` | 系统错误码 | PPT 无 |

第 14 页大意：会议 ID + 通过/不通过 + **逐条规则与原因** + 校验次数。

### 2.2 `rule_results[]` ↔ PPT 12 / 13 / 14（你真正要做的）

| rule_code | 审什么 | PPT |
|-----------|--------|-----|
| `ASSET_TYPE_CHECK` | 类别 vs 声明 type | 14-1；12「设计 type」 |
| `CLARITY` | 清晰度 | 12、13、14 |
| `KEY_FIELD_MATCH` | 日期时间地点讲者名一致 | 12/13 要求1；14-2 |
| `TIME_CONSISTENCY` | 各图时间一致（大讲堂） | 12 点6；14-3 |
| `BAYER_LOGO` | 拜耳 Logo | 12-2；13-2；14-4 |
| `PANORAMA_COUNT` | 全景人数 | 12≥35；13 单≥6/双≥12；14-5 |
| `SIGNIN_DURATION` | 签到时长 | 12>120；13 单>30/双>60；14-7 |
| `SIGNIN_RATIO_AND_STORES` | 1:6 + ≥2 门店（微型） | 13-3；14-6 |
| `IMAGE_DUP` | 未盗用他场现场照（全部照片 vs 其他会议） | pHash/embedding；**不查会内** |
| `TOPIC_REUSE` | 讲者照主题/标题不与历史重复 | OCR → 归一化 → 字符串；**仅讲者照** |
| `WATERMARK_CONSISTENCY` | 水印时间地点（建议） | PPT 未写死；样例常见 |
| `SPEAKER_TOPIC_OCR` | 课件标题 vs topic | 12；14-9 |
| `SPEAKER_SHOT_PAIR` | 每讲者两类照 | 12 各 2 张 |
| `NAME_CARD_SPEAKER_MATCH` | 台卡名 = 系统讲者 | 12 台卡；**你后补** |
| `NAME_CARD_TEMPLATE` | 台卡版式（可选） | **你后补 / crop** |
| `HANDBOOK_DETECT` | 是否宣传手册 | 12 手册名；**你后补** |
| `HANDBOOK_NOT_STALE` | 旧版手册 | **你后补** |
| `PPT_TEMPLATE_MATCH` | 现场 PPT vs 规定模版 | 13 权益两页；**你后补** |
| `PPT_PAGE_KIND` | 介绍页 vs 日程页 | 13 点6 |

每条还有：`status` / `confidence` / `reason_text` / `evidence` → 第 14 页「逐条规则结果」。

### 2.3 `asset_results[]`

| 模式 | 内容 | PPT |
|------|------|-----|
| **simple** | `asset_status` + `fail_reasons`（系统展示必须） | 14「不通过原因」落到具体照片 |
| **full** | 另加清晰度、`checks`、`ocr_fields`/`ocr_raw`、detections、主题复用 hit | 12/13 提取比对；14 规则1 |

---

## 3. 你后补的需求清单（自检）

| 你说的 | 落在哪 | PPT 底 |
|--------|--------|--------|
| 台卡、手册单独材料和规则 | Input `NAME_CARD`/`HANDBOOK`；规则见上 | 第 12 页已有材料 |
| 台卡名字 vs 系统名字 | `NAME_CARD_SPEAKER_MATCH` | 第 12 台卡四名 |
| 手册能否认出宣传手册 + 旧照片/旧版 | `HANDBOOK_DETECT` + `HANDBOOK_NOT_STALE` | 第 12 手册名；旧版你补 |
| PPT 模版是否一致 | `PPT_TEMPLATE_MATCH`（+ `PPT_PAGE_KIND`） | 第 13 权益两页 PPT |
| 模版从照片示例 crop | [04-template-pack.md](04-template-pack.md)；请求可带 `template_pack_version` | PPT 无「crop」二字；实现手段 |

---

## 4. PPT 有、但不进你的 I/O（PE 做）

| 内容 | PPT | 谁 |
|------|-----|-----|
| 同月讲者 1 次、同期 ≤3、主题不重复 | 7、12、14 | PE |
| 表单侧时长、人数公式（如 ≥39、表单 1:6） | 7、9、12、13 | PE（你另做全景/签到 OCR） |
| 听众同专题仅一次 | 12、13、14 | 双方都做不了 |
| 状态机、导入草稿、展示「AI 校验次数」 | 5 | PE |

---

## 5. 一张总图

```text
PPT 7/9  表单字段     →  INPUT form / speakers
PPT 12/13 照片清单    →  INPUT assets[].asset_type + s3_uri
PPT 14   传入 type    →  INPUT asset_type
你后补 台卡/手册/PPT  →  内部规则；OUTPUT rule_results

PPT 5/14 通过不通过+原因 → OUTPUT overall_status + summary_* + rule_results
PPT 12-14 AI 规则清单    → OUTPUT 各 rule_code
```

---

## 6. 自己实现时看哪份

1. 跟 PE 对字段 → [PE接口文档-v1.8.md](PE接口文档-v1.8.md)  
2. 写审核逻辑 → [03-rule-matrix.md](03-rule-matrix.md)  
3. 做模版比对 → [04-template-pack.md](04-template-pack.md)  
4. 忘了「这项对应 PPT 哪」→ **看本文**  
