# 检测点清单 · photo_results · 图片查重与主题不重复

> 回应导师反馈：每个检测点要有清晰 true/false；说清 `photo_results`；跨会议重复怎么做。  
> **PE simple 契约**见 [README-PE-simple对接.md](README-PE-simple对接.md)。本文侧重 **full** 的 `checks` / 查重算法；历史全文见 [PE接口文档-v1.8.md](PE接口文档-v1.8.md)。

**两类「重复」不要混（已定）：**

| 需求 | 比什么 | 做法 |
|------|--------|------|
| **主题/标题重复** | 文字：课件标题 / 讲题 | OCR 出标题 → 归一化 → 和历史主题**字符串**比（仅讲者照） |
| **照片重复（盗用他场现场照）** | 图像本身 | **pHash / embedding** 与**其他会议**历史图比（本场全部照片）；一致或近似都算 |

> **不做**会议内部「两张图是否相似」的比对；照片查重只查**跨会议**混用/盗用。

**命名约定（避免歧义）：**  
一律用**正向语义**：`true` = 满足合格条件，`false` = 不满足，`null` = 本张图不适用或无法判定（配合 `uncertain_checks`）。  
例如：`has_bayer_logo: true` = 有拜耳 Logo（合格）。

---

## 0. 返回两种模式（先看这个）

| 模式 | 给谁 | PE/系统要什么 | 里面有什么 |
|------|------|---------------|------------|
| **simple**（默认） | PE 系统 | 整场结论 + 哪张不合格 + 机器原因码 | 仅 `task_id` / `meeting_id` / `overall_status` / `photo_results[{photo_id, photo_status, fail_reasons[{reason_code}]}]`（ERROR 时加 `error`） |
| **full** | AI 开发 debug | 尽量全，方便纠错 | 落库完整形态：`checks`、OCR、detections、evidence、`rule_results`、`debug` 等 |

- 查询：`GET .../retail_meeting_checks/{task_id}?mode=simple|full`  
- 回调：默认 simple；提交时可 `options.response_mode`  
- 服务端始终算全量并落库；mode 只裁剪返回（见 `app/services/projection.py`）  

下文 §1～§3 的 `checks` 清单，主要出现在 **full**；simple 只带 `reason_code`，中文文案由 PE 本地映射。

---

## 1. 输出怎么看「查了什么、结果是什么」

| 模式 | 怎么拉清单 |
|------|------------|
| **simple** | 遍历 `photo_results`：看 `photo_status`；`FAIL`/`UNCERTAIN` 时读 `fail_reasons[].reason_code` → PE 映射文案 |
| **full** | 另加：摊开每张 `checks` true/false；场级看 `rule_results`（含 `evidence`）；`fail_reasons` 可含 `reason_text` / `check` |

| 层级 | 字段 | 作用 |
|------|------|------|
| **按张（simple）** | `photo_status` + `fail_reasons[].reason_code` | PE 展示必须 |
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
| `detected_type` | string/null | AI 识别的类别（full） |
| `type_match` | bool/null | 声明与识别是否一致 |
| `clarity_score` | float/null | 清晰度 0~1 |
| `is_clear` | bool/null | 是否够清晰（达标为 true） |
| `checks` | object | **检测点清单**：key=检测点名，value=`true`/`false`/`null` |
| `uncertain_checks` | string[] | 值为 null 或拿不准、建议人工的检测点名 |
| `ocr_fields` | object/null | 抽出的日期/时间/地点/姓名等（给人看/比对） |
| `image_dup_hit` | bool | 本张是否与**其他会议**照片重复（完全一致或近似相似） |
| `image_dup_kind` | string/null | `exact` \| `similar`（命中时标明） |
| `image_dup_score` | float/null | 相似度 0~1（近似命中时） |
| `image_dup_ref_session_no` / `image_dup_ref_meeting_id` | | 撞到的**历史场次/会议**（跨会议混用） |
| `topic_reuse_hit` | bool | **讲者照**抽出的标题是否与历史主题重复 |
| `topic_reuse_ref_session_no` | string/null | 撞到的历史场次 |
| `topic_text_ocr` | string/null | 讲者照 OCR 标题（非讲者照一般为 null） |
| `fetch_error` | object/null | 下载失败时才有 |

### 2.2 示例（日程海报一张）

```json
{
  "photo_id": "201",
  "photo_type": "Poster",
  "photo_status": "PASS",
  "fail_reasons": [],
  "detected_type": "Poster",
  "type_match": true,
  "clarity_score": 0.91,
  "is_clear": true,
  "checks": {
    "type_match": true,
    "is_clear": true,
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
| `type_match` | 类别与声明一致 | 不一致 |
| `is_clear` | 清晰度达标 | 模糊 |
| `image_not_duplicated` | 未盗用其他会议现场照（见 §4.A） | pHash/embedding 命中其他会议（跨会；不查会内） |

### 3.2 大讲堂 · 海报 / 展架（Poster / Stand / EDM）

| 检测点 key | true 表示 |
|------------|-----------|
| `has_bayer_logo` | 含拜耳 Logo |
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
| `name_card_template_ok` | 台卡版式与规定模版一致（可选） |

### 3.4 大讲堂 · 手册（Manual）

| 检测点 key | true 表示 |
|------------|-----------|
| `handbook_detected` | 识别为规定宣传手册 |
| `handbook_not_stale` | 非旧版封面 |

### 3.5 大讲堂 · 讲者照（SpeakerTitle）

| 检测点 key | true 表示 |
|------------|-----------|
| `topic_matches_form` | 标题合影时课件标题与该讲者 `topic` 一致（仅 SpeakerTitle；与表单比对） |
| `topic_not_reused_in_period` | OCR 标题未与历史会议重复（**仅讲者照**；见 §4.B；SpeakerLecture 无标题则 null） |
| `speaker_name_visible_ok` | 能关联到正确讲者（若可抽名） |

> 讲者照同时做：通用 **图片查重** + **主题不重复**（抽标题）。

### 3.6 全景（Panorama）

| 检测点 key | true 表示 |
|------------|-----------|
| `people_count_recorded` | 成功得到本张人数（具体人数在 ocr_fields/detections 里） |

> 是否 ≥35 / ≥6 / ≥12 是**场级**规则（多张合计），放在 `rule_results` 的 `PANORAMA_COUNT`，不要单张硬判 false。

### 3.7 签到表（SignSheet）

| 检测点 key | true 表示 |
|------------|-----------|
| `signin_template_ok` | 像标准签到模版（可选） |
| `duration_readable` | 起止时间可读 |
| `duration_meets_threshold` | 单张能算出时长且达标（若跨多页则场级再汇总） |

微型另有场级：`SIGNIN_RATIO_AND_STORES`（1:6、两门店）→ `rule_results`。

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

> 展示照做 **图片查重**；主题文字查重仍只在讲者照上做。

### 3.9 场级规则（不在单张 checks 里，在 rule_results）

| rule_code | 说明 |
|-----------|------|
| `PANORAMA_COUNT` | 多张全景人数合计是否达标 |
| `IMAGE_DUP` | 是否盗用他场现场照（pHash/embedding，仅跨会，见 §4.A） |
| `TOPIC_REUSE` | **讲者照** OCR 标题是否与历史会议主题重复（见 §4.B） |
| `TIME_CONSISTENCY` | 多图时间是否一致 |
| `KEY_FIELD_MATCH` | 跨材料交叉比对汇总 |
| `SPEAKER_SHOT_PAIR` | 每位讲者是否两类照齐全 |
| `SIGNIN_RATIO_AND_STORES` | 微型签到人数与门店 |
| `PPT_PAGE_KIND`（场级） | 两张展示是否互补为介绍+日程 |

`rule_results` 里建议增加与 checks 对齐的布尔可读法：

```json
{
  "rule_code": "BAYER_LOGO",
  "passed": true,
  "status": "PASS",
  "reason_text": "海报与展架均检出拜耳Logo"
}
```

`passed: true/false` 与 `status` 并存：清单党看 `passed`，细节看 `status`（含 UNCERTAIN→可当 passed=null）。

---

## 4. 两类查重（分开做）

### 4.A 照片重复（盗用他场现场照 · 跨会议 · pHash/embedding）

| 项 | 说明 |
|----|------|
| 需求 | 不同会议之间是否**混用/盗用**了现场照 |
| 比什么 | **图像本身** |
| 做法 | 算 **pHash** 和/或 **embedding** → 与 `image_dup_history` 里**其他会议**比 |
| 对本场哪些图 | **全部照片** |
| 和谁比 | 仅**其他 `meeting_id`**；范围 `refs.image_dup_search_scope`：`period`（默认）| `all` |
| 判定 | pHash 距离 ≤ 阈值，或 embedding 相似度 ≥ 阈值 → 重复（含近似） |
| 命中 | `image_not_duplicated=false`；场级 `IMAGE_DUP` FAIL；记下历史场次 |
| 入库 | 本场结束后写入指纹 |
| **不做** | **不查会议内部**两张图是否相似 |

```text
本场每张图 → phash / embedding
  → 只查其他会议历史指纹 → 越阈则盗用 FAIL
  → 本场指纹入库
```

### 4.B 主题/标题重复（仅讲者照 · 文字）

| 项 | 说明 |
|----|------|
| 需求 | 讲课主题 / 课件标题是否与历史重复 |
| 比什么 | **文字**（课件标题 / 讲题） |
| 做法 | OCR 出标题 → **归一化** → 和历史主题**字符串**比 |
| 对哪些图 | **仅 `SpeakerTitle`** |
| 和谁比 | `topic_history`（排除当前会议；`refs.topic_search_scope`） |
| 命中 | `topic_not_reused_in_period=false`；场级 `TOPIC_REUSE` FAIL |
| 入库 | 讲者照标题写入 `topic_history` |

```text
讲者 `SpeakerTitle` → OCR → 归一化 → 与 topic_history 字符串比 → 命中则主题重复
```

### 4.C 对照

| | 主题/标题重复 | 照片重复（盗用他场） |
|--|----------------|----------------------|
| 比什么 | 文字 | 图像本身 |
| 做法 | OCR → 归一化 → 字符串 | pHash / embedding |
| 范围 | 讲者照 | 全部照片 vs **其他会议** |
| 不做 | — | **不查会内相似图** |
| 规则码 | `TOPIC_REUSE` | `IMAGE_DUP` |
| 检测点 | `topic_not_reused_in_period` | `image_not_duplicated` |

手册「旧版」仍用 `handbook_not_stale`（封面模版），与上述两类无关。

---
