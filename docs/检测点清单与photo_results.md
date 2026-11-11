# 检测点清单 · photo_results · 图片查重与主题不重复

> 回应导师反馈：每个检测点要有清晰 true/false；说清 `photo_results`；跨会议重复怎么做。  
> **PE simple 契约**见 [README-PE-simple对接.md](README-PE-simple对接.md)。本文侧重 **full** 的 `checks` / 查重算法；历史全文见 [PE接口文档-v1.8.md](PE接口文档-v1.8.md)。

**两类「重复」不要混（已定）：**

| 需求 | 比什么 | 做法 |
|------|--------|------|
| **主题/标题重复** | 文字：课件标题 / 讲题 | OCR 出标题 → 归一化 → 和历史主题**字符串**比（仅讲者照） |
| **照片重复（盗用他场现场照）** | 图像本身 | 与**其他会议**库比（1×同组）：有人物↔有人物，无人物↔无人物；有人物/手册用 pHash+embedding；**海报/电子海报/展架仅完全一致** |

> **不做**会议内部「两张图是否相似」的比对；照片查重只查**跨会议**混用/盗用。

**命名约定（避免歧义）：**  
一律用**正向语义**：`true` = 满足合格条件，`false` = 不满足，`null` = 本张图不适用或无法判定（配合 `uncertain_checks`）。  
例如：`has_bayer_logo: true` = 有拜耳 Logo（合格）。

---

## 0. 返回两种模式（先看这个）

| 模式 | 给谁 | PE/系统要什么 | 里面有什么 |
|------|------|---------------|------------|
| **simple**（默认） | PE 系统 | 整场结论 + 仅不合格图 + 原因码与中文 | 见 `AI_接口文档v2.md`：`flagged_photos`（`FAIL`/`ERROR`/`NEED_HUMAN`）；PASS 不下发；ERROR 时 `flagged_photos=[]` |
| **full** | AI 开发 debug | 尽量全，方便纠错 | 落库完整形态：`checks`、OCR、detections、evidence、`rule_results`、`debug` 等 |

- 查询：`GET .../retail_meeting_checks/{task_id}?mode=simple|full`  
- 回调：默认 simple；提交时可 `options.response_mode`  
- 服务端始终算全量并落库；mode 只裁剪返回（见 `app/services/projection.py`）  

下文 §1～§3 的 `checks` 清单，主要出现在 **full**；simple 带 `reason_code` + `comments`（中文后处理；ERROR 除外）。

---

## 1. 输出怎么看「查了什么、结果是什么」

| 模式 | 怎么拉清单 |
|------|------------|
| **simple** | 遍历 `flagged_photos`：看 `photo_status`；读 `fail_reasons[].reason_code` + `comments`；未列出的材料视为通过 |
| **full** | 另加：摊开每张 `checks` true/false；场级看 `rule_results`（含 `evidence`）；`fail_reasons` 可含 `reason_text` / `check` |

| 层级 | 字段 | 作用 |
|------|------|------|
| **按张（simple）** | 仅非 PASS：`photo_status` + `fail_reasons[].reason_code` + `comments` | PE 展示必须 |
| **按张（full）** | `checks` | 每个检测点 true/false/null |
| **按规则/场次（full）** | `rule_results[]` | 跨多张汇总（如全景人数、**跨会议主题是否重复**）；simple **不返回** |

---

## 2. `photo_results` 是什么

**每一张材料（每个 `photo_id`）一条记录**，描述：这张图本身怎样 + 在这张图上做了哪些检测点。

### 2.1 每条必含 / 常用字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `photo_id` | string | 对应请求里的材料 ID（≤36） |
| `photo_type` | string | PE 声明的材料类型（CRM `PhotoType`） |
| `photo_status` | string | `PASS` / `FAIL` / `UNCERTAIN` / `ERROR` |
| `fail_reasons` | array | 不合格/待人工原因；通过时为空 |
| `checks` | object | **检测点清单**：key=检测点名，value=`true`/`false`/`null` |
| `uncertain_checks` | string[] | 值为 null 或拿不准、建议人工的检测点名 |
| `ocr_fields` | object/null | 抽出的日期/时间/地点/姓名等（给人看/比对） |
| `image_dup_hit` | bool | 本张是否与**其他会议**照片重复（完全一致或近似相似） |
| `image_dup_kind` | string/null | `exact` \| `similar`（命中时标明） |
| `image_dup_score` | float/null | 相似度 0~1（近似命中时） |
| `image_dup_ref_session_no` / `image_dup_ref_meeting_id` | | 撞到的**历史场次/会议**（跨会议混用） |
| `topic_text_ocr` | string/null | 讲者照 OCR 标题（非讲者照一般为 null） |
| `fetch_error` | object/null | 下载失败时才有 |

### 2.2 示例（日程海报一张）

```json
{
  "photo_id": "201",
  "photo_type": "Poster",
  "photo_status": "PASS",
  "fail_reasons": [],
  "checks": {
    "has_bayer_logo": true,
    "date_matches_form": true,
    "time_matches_form": true,
    "location_matches_form": true,
    "speakers_match_form": true
  },
  "uncertain_checks": [],
  "ocr_fields": {
    "meeting_date": "2026-04-17",
    "meeting_time": "14:00",
    "location": "信阳市六合春宴酒店（信阳师范大学店）",
    "speaker_names": ["高芳", "袁芳", "刘亭", "余艳红"]
  }
}
```

---

## 3. 检测点清单（按材料类型）

下列 `checks` 中：`true`=合格侧成立；不适用的类型不要硬塞 false，用 `null` 或根本不出现该 key（推荐：**不适用则 null**，清单列全便于拉表）。

### 3.1 通用（几乎每张图）


| 检测点 key | true 表示 | false 表示 |
|------------|-----------|------------|
| `image_not_duplicated` | 未盗用其他会议现场照（见 §4.A） | pHash/embedding 命中其他会议（跨会；不查会内） |

### 3.2 大讲堂 · 海报 / 展架（Poster / Stand / EDM）

| 检测点 key | true 表示 |
|------------|-----------|
| `has_bayer_sponsor` | 图片最下方页脚含赞助方全称「拜耳医药保健有限公司」（不要求十字 Logo） |
| `date_matches_form` | 日期与表单一致 |
| `time_matches_form` | 时间与表单一致 |
| `location_matches_form` | 地点与 `form.meeting_location` 一致 |
| `speakers_match_form` | 讲者名与表单集合一致（能识别到的范围内） |

> 海报/展架做 **图片查重**（通用 `image_not_duplicated`），**不做**主题文字查重。

### 3.3 大讲堂 · 台卡（TableCard）

| 检测点 key | true 表示 |
|------------|-----------|
| `name_card_count_ok` | 识别到的台卡人数与讲者人数一致（如 4） |
| `name_set_matches_speakers` | OCR 姓名集合 = 系统讲者姓名集合 |

### 3.4 大讲堂 · 手册（Manual）

| 检测点 key | true 表示 |
|------------|-----------|
| `handbook_detected` | 识别为规定宣传手册 |
| `handbook_not_stale` | 非旧版封面 |

### 3.5 大讲堂 · 讲者照（SpeakerTitle / SpeakerLecture）

| 检测点 key | true 表示 |
|------------|-----------|
| `speaker_title_composition_ok` | **SpeakerTitle**：同时有讲者、标题、讲者姓名、日期 |
| `has_speaker_person` / `has_topic_title` / `has_speaker_name` / `has_date` | 标题合影各要素 |
| `speaker_lecture_composition_ok` | **SpeakerLecture**：同时有讲者与 PPT/投影 |
| `has_ppt_screen` | 授课照可见 PPT/投影 |
| `topic_matches_form` | 课件标题与该讲者 `topic` 一致（**仅 SpeakerTitle**） |
| `speaker_name_visible_ok` | 能关联到正确讲者（**仅 SpeakerTitle**） |

> 讲者照同时做：通用 **图片查重** + 构图完整（`SPEAKER_COMPOSITION`）+ 标题合影主题对台账。

### 3.6 全景（Panorama）

| 检测点 key | true 表示 |
|------------|-----------|
| `people_count_recorded` | 成功得到本张人数（具体人数在 ocr_fields/detections 里） |

> 是否 ≥35 / ≥6 / ≥12 是**场级**规则（多张合计），放在 `rule_results` 的 `PANORAMA_COUNT`，不要单张硬判 false。

### 3.7 签到表（SignSheet）

> **多张合并**：一场若上传 ≥2 张 `SignSheet`，时长 / 听众人数 / 门店视为**一场检查**（各页 `checks` 共用合并结果）。时长取可读页的最大值；听众人数按页累加；门店名取并集。读不出时长 → `OCR_LOW_CONFIDENCE`。  
> **填写与人数拆开**：① **填写**（`signin_complete_ok` / `SIGNIN_COMPLETE`）每页各自核验；② **人数**（`signin_audience_ok` / `SIGNIN_AUDIENCE`）多页合计。不做签到表模版/是否印刷表判定。

| 检测点 key | true 表示 |
|------------|-----------|
| `duration_readable` | 合并后能读出起止时间 / 时长 |
| `duration_meets_threshold` | 合并时长达标（大讲堂 >120；微型单 >30 / 双 >60） |
| `signin_complete_ok` | **本页**填写完整：表头（若有）时间/时长/地点已填；已占用行除「其他」列外均已填；末尾空行可不填 |
| `signin_audience_ok` | **场级合并**听众人数达标（大讲堂 ≥35；微型 ≥ 讲者×6）；各页共用合并结果 |

场级：`SIGNIN_COMPLETE` → `SIGNIN_INCOMPLETE`；`SIGNIN_AUDIENCE` → `SIGNIN_COUNT_BELOW`。

### 3.8 微型 · 权益展示（EDMDisplay / ProjectIntro）

业务约定（模版特征，优先于抽象「像不像 PPT」）：

| 材料 | 对应 | 模版检测要点 |
|------|------|--------------|
| **权益一** | `ProjectIntro` | 规定模版上是否有 **彩色丝带 / 彩色波浪装饰条**（`has_colorful_ribbon`） |
| **权益二** | `EDMDisplay` | 规定模版上是否有 **日程表**（`has_agenda_table`，时间/内容/人员等表格） |

| 检测点 key | true 表示 |
|------------|-----------|
| `has_bayer_logo` | 投影/画面含拜耳 Logo |
| `has_colorful_ribbon` | **权益一**：模版底部彩色丝带可见 |
| `has_agenda_table` | **权益二**：模版上日程表可见 |
| `ppt_template_match` | 对应该页特征成立（一=丝带，二=日程表） |
| `ppt_page_kind_ok` | 页类正确（介绍页 / 日程页） |

> 展示照做 **图片查重**。

### 3.9 场级规则（不在单张 checks 里，在 rule_results）

| rule_code | 说明 |
|-----------|------|
| `PANORAMA_COUNT` | 多张全景人数合计是否达标 |
| `IMAGE_DUP` | 是否盗用他场现场照（pHash/embedding，仅跨会，见 §4.A） |
| `TIME_CONSISTENCY` | 海报等材料日程时间是否落在会议时段（不做时间水印） |
| ~~`WATERMARK_CONSISTENCY`~~ | 已下线（时间/日期/地点水印均不审） |
| `KEY_FIELD_MATCH` | 跨材料交叉比对汇总 |
| `SPEAKER_SHOT_PAIR` | 每位讲者是否两类照齐全 |
| `SIGNIN_COMPLETE` | 签到表填写完整 |
| `SIGNIN_AUDIENCE` | 签到表听众人数 |

`rule_results` 里建议增加与 checks 对齐的布尔可读法：

```json
{
  "rule_code": "BAYER_LOGO",
  "passed": true,
  "status": "PASS",
  "reason_text": "赞助方「拜耳医药保健有限公司」均已检出"
}
```

`passed: true/false` 与 `status` 并存：清单党看 `passed`，细节看 `status`（含 UNCERTAIN→可当 passed=null）。

---

## 4. 两类查重（分开做）

### 4.A 照片重复（盗用他场现场照 · 跨会议 · 分组查重）

| 项 | 说明 |
|----|------|
| 需求 | 不同会议之间是否**混用/盗用**了现场照 / 材料图 |
| 比什么 | **图像本身**（本场每张 vs 库内**同组全部**历史图，非会内两两） |
| 分组 | **有人物**：`SpeakerTitle` / `SpeakerLecture` / `Panorama`；**无人物**：`Manual` / `Poster` / `Stand` / `EDM` / `EDMDisplay` / `ProjectIntro`。两组互不交叉 |
| 做法 | 有人物 + 手册/介绍：`pHash`（距离阈值）和/或 **embedding 余弦**；**海报 / 电子海报 / 展架**（`Poster`/`EDM`/`EDMDisplay`/`Stand`）：**仅 pHash 完全一致**（distance=0），不算余弦 |
| 对本场哪些图 | 上表分组内材料（台卡/签到表不参与） |
| 和谁比 | 仅**其他 `meeting_id`** 且**同组**；范围 `refs.image_dup_search_scope`：`period`（默认）| `all` |
| 判定 | 见「做法」；命中则重复 |
| 命中 | `image_not_duplicated=false`；场级 `IMAGE_DUP` FAIL；记下历史场次 |
| 入库 | 本场结束后写入同组指纹 |
| **不做** | **不查会议内部**两张图是否相似；海报类不做 embedding |

```text
本场每张图（按有人/无人分组）→ phash（海报类）/ phash+embedding（其余）
  → 只查其他会议、同组历史指纹 → 命中则盗用 FAIL
  → 本场指纹入库
```

~~主题/标题跨会复用（原 §4.B / `TOPIC_REUSE`）已下线。~~ 手册「旧版」仍用 `handbook_not_stale`（封面模版），与照片查重无关。

---
