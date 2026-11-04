# 药师会零售会议材料检查 · PE 接口文档 v1.8

| 项 | 内容 |
|----|------|
| 文档版本 | v1.8 |
| API 版本 | v1 |
| 更新日期 | 2026-10-23 |
| 适用对象 | PE 系统开发 / 测试；AI 排障可用 `full` |
| OpenAPI | [openapi/pe-retail-meeting-check.v1.yaml](openapi/pe-retail-meeting-check.v1.yaml) |
| JSON Schema | [schemas/retail-meeting-check-request.schema.json](schemas/retail-meeting-check-request.schema.json) · [schemas/retail-meeting-check-response.schema.json](schemas/retail-meeting-check-response.schema.json) |

**变更记录**

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.8 | 2026-10-23 | 两类查重定稿：主题=OCR文字；照片盗用= pHash/embedding **仅跨会议**（不查会内相似） |
| v1.7 | 2026-10-23 | 拆开两类查重：图片查重 vs 主题不重复（仅讲者照） |
| v1.6 | 2026-10-23 | 响应分 **`simple` / `full` 两种模式**：simple 给 PE 展示（哪张不合格+原因）；full 给 AI debug（字段尽量全） |
| v1.5 | 2026-10-23 | （已 superseded）曾将主题 OCR 扩到全部照片；现改回仅讲者照，图片一致另立规则 |
| v1.4 | 2026-10-23 | 主路径改为 `/v1/retail_meeting_checks`；类型名改为 `RetailMeetingCheckRequest/Response` |
| v1.3 | 2026-10-23 | 跨会议查重定义为**主题/标题重复**（非图像盗用） |
| v1.2 | 2026-10-23 | `asset_results.checks` 布尔检测点清单；`rule_results.passed`；查重说明 |
| v1.1 | 2026-10-22 | 改为以接口清单为主体；删除一页纸摘要 |
| v1.0 | 2026-10-22 | 首版 |

---

## 1. 接口清单（全部）

PE 与 AI **零售会议材料检查**相关的接口如下。材料**只传 S3 地址**，不传文件二进制。

| 序号 | 方向 | 方法 | 路径 | 说明 | 成功码 |
|------|------|------|------|------|--------|
| 1 | PE → AI | `POST` | `/v1/retail_meeting_checks` | 提交一场会议的材料检查 | `202` |
| 2 | PE → AI | `GET` | `/v1/retail_meeting_checks/{request_id}` | 查询检查进度/结果 | `200` |
| 3 | AI → PE | `POST` | `{X-Callback-URL}` | 检查完成回调（可选；由 PE 提供 URL） | `2xx` |
| 4 | PE → AI | `GET` | `/health` | 健康检查（连通性） | `200` |

**调用关系：**

```text
PE 提交 POST /v1/retail_meeting_checks ──202──► 拿到 request_id / job_id
        │
        ├─ 轮询 GET /v1/retail_meeting_checks/{request_id} 直到终态
        │
        └─ 或等待 AI 回调 POST {callback_url}（若提交时带了 X-Callback-URL）
```

**终态 `overall_status`：** `PASS`（通过）· `FAIL`（不通过）· `NEED_HUMAN`（待人工）· `ERROR`（系统错误，非业务不合格）

---

## 2. 公共约定

### 2.1 Base URL

| 环境 | Base URL（上线前替换） |
|------|------------------------|
| 测试 | `https://retail-meeting-check-test.example.com` |
| 生产 | `https://retail-meeting-check.example.com` |

### 2.2 鉴权（接口 1、2、4）

```http
Authorization: Bearer <YOUR_API_TOKEN>
```

Token 由 AI 侧按环境发放。未带或无效 → `401`；无权限 → `403`。

### 2.3 通用规则

| 项 | 约定 |
|----|------|
| 协议 | HTTPS，`Content-Type: application/json`，UTF-8 |
| 幂等 | 相同 `request_id` 不重复计次，返回首次结果 |
| 重提 | 用户改材料后再审 → **换新** `request_id` |
| S3 | `s3://{bucket}/{key}`；AI 需有只读权限 |
| 轮询建议 | 首次 3s，之后每 5s，最长约 10 分钟 |
| 限流 | 默认 60 次/分钟/Token，超限 `429` |

### 2.4 职责边界

| 方 | 做什么 |
|----|--------|
| PE | 组请求、上传 S3、调接口、按结果改会议状态 |
| AI | 读图做材料检查、返回结构化结果 |
| 不做（PE 自理） | 讲者次数/主题不重复、表单时长等业务规则 |

---

## 3. 接口 1：提交材料检查

| 项 | 内容 |
|----|------|
| 方法 / 路径 | `POST /v1/retail_meeting_checks` |
| 说明 | 提交一场会议材料检查任务（异步） |
| 成功 | `202 Accepted` |
| 幂等键 | Body.`request_id` |

### 3.1 请求头

| Header | 必填 | 说明 |
|--------|------|------|
| Authorization | 是 | `Bearer <token>` |
| Content-Type | 是 | `application/json` |
| X-Callback-URL | 否 | 完成后回调的 HTTPS 地址；不传则只靠轮询 |
| Idempotency-Key | 否 | 若传须与 `request_id` 一致 |

### 3.2 请求体字段

**顶层**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| request_id | string | 是 | 请求唯一 ID，8~64 字符 |
| meeting_id | integer | 是 | PE 会议主键 |
| session_no | string | 是 | 场次编号，≤20 |
| project_type | string | 是 | `LECTURE_HALL` \| `MICRO` |
| meeting_subtype | string/null | 条件 | 微型：`SINGLE`\|`DUAL`；大讲堂：`null` |
| period_id | integer | 是 | 项目期数 ID |
| form | object | 是 | 会议表单 |
| assets | array | 是 | 材料列表，≥1 |
| refs | object | 否 | 模版包/主题查重范围 |
| options | object | 否 | 阈值等 |

**form**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| meeting_name | string | 是 | 会议名称 |
| meeting_date | string | 是 | `YYYY-MM-DD` |
| start_time | string | 是 | `HH:mm` |
| end_time | string | 是 | `HH:mm` |
| chain_or_store_name | string | 是 | 大讲堂=连锁名；微型=药店名 |
| location | string | 是 | 会议地点（与海报/水印比对） |
| remark | string | 否 | 备注 |
| total_attendees | integer | 是 | 总参会人数 |
| speakers | array | 是 | 讲者列表，≥1 |

**speakers[]**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| speaker_id | integer | 是 | 讲者 ID |
| speaker_name | string | 是 | 姓名 |
| topic | string | 是 | 讲题 |
| store_name | string | 是 | 所属门店 |
| service_minutes | integer | 是 | 服务时长（分钟） |
| role_title | string | 否 | 身份 |
| fee / tax | number | 否 | 讲课费 / 税金 |

**assets[]**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| asset_id | integer | 是 | 材料 ID |
| asset_type | string | 是 | 见下表枚举 |
| s3_uri | string | 是 | `s3://bucket/key` |
| content_type | string | 是 | `image/jpeg` \| `image/png` \| `application/pdf` |
| sort_no | integer | 否 | 同类型多张顺序 |
| speaker_id | integer | 条件 | 讲者照必填 |
| speaker_shot_kind | string | 条件 | `TITLE_GROUP` \| `LECTURING` |

**asset_type（大讲堂）**

| 码 | 含义 | 数量 |
|----|------|------|
| E_POSTER | 电子日程海报 | ≥1 |
| POSTER | 日程海报 | ≥1 |
| STAND | 日程展架 | ≥1 |
| NAME_CARD | 台卡 | ≥1 |
| HANDBOOK | 手册 | ≥1 |
| SPEAKER_PHOTO | 讲者照 | 每讲者 2 张 |
| PANORAMA | 全景 | ≥1 |
| SIGNIN | 签到表 | ≥1 |

**asset_type（微型）**

| 码 | 含义 | 数量 |
|----|------|------|
| E_POSTER | 电子日程海报 | ≥1 |
| E_POSTER_DISPLAY | 电子日程海报展示 | ≥1 |
| PROJECT_INTRO_DISPLAY | 项目介绍展示 | ≥1 |
| SPEAKER_PHOTO | 讲者标题合影 | 单 1 / 双 2 |
| PANORAMA | 全景 | ≥1 |
| SIGNIN | 签到表 | ≥1 |

**refs / options（可选）**

| 字段 | 说明 |
|------|------|
| refs.template_pack_version | 模版包版本，如 `2026Q2` |
| refs.logo_ref_s3 | Logo 参考图 |
| refs.topic_search_scope | 主题跨会议检索范围：`period`（默认）\| `all`（兼容旧名 `duplicate_search_scope`） |
| refs.image_dup_search_scope | 图片跨会议检索范围：`period`（默认）\| `all` |
| options.clarity_threshold | 默认 0.6 |
| options.human_confidence_threshold | 默认 0.75 |
| options.watermark_time_skew_minutes | 默认 120 |
| options.name_match_mode | `exact` \| `fuzzy`（默认） |
| options.response_mode | 回调默认响应模式：`simple`（默认）\| `full`；查询接口可用 query `mode` 覆盖 |
| options.image_phash_max_distance | 图片近似相似：pHash 汉明距离上限，默认 10 |
| options.image_similarity_threshold | 图片近似相似：embedding 相似度下限，默认 0.92 |

### 3.3 请求示例（微型）

```bash
curl -X POST 'https://retail-meeting-check-test.example.com/v1/retail_meeting_checks' \
  -H 'Authorization: Bearer YOUR_API_TOKEN' \
  -H 'Content-Type: application/json' \
  -d @- <<'EOF'
{
  "request_id": "req-micro-000090-001",
  "meeting_id": 1090,
  "session_no": "000090",
  "project_type": "MICRO",
  "meeting_subtype": "SINGLE",
  "period_id": 2,
  "form": {
    "meeting_name": "单讲师",
    "meeting_date": "2026-05-27",
    "start_time": "14:00",
    "end_time": "14:35",
    "chain_or_store_name": "老百姓大药房连锁（安徽）有限公司",
    "location": "合肥市老百姓大药房连锁（安徽）有限公司淠河路店",
    "total_attendees": 7,
    "speakers": [
      {
        "speaker_id": 1,
        "speaker_name": "示例讲者",
        "topic": "慢病管理",
        "store_name": "淠河路店",
        "service_minutes": 30
      }
    ]
  },
  "assets": [
    {"asset_id": 301, "asset_type": "E_POSTER", "s3_uri": "s3://pe-meetings/micro/000090/agenda.png", "content_type": "image/png"},
    {"asset_id": 302, "asset_type": "E_POSTER_DISPLAY", "s3_uri": "s3://pe-meetings/micro/000090/display1.jpg", "content_type": "image/jpeg"},
    {"asset_id": 303, "asset_type": "PROJECT_INTRO_DISPLAY", "s3_uri": "s3://pe-meetings/micro/000090/intro.jpg", "content_type": "image/jpeg"},
    {"asset_id": 304, "asset_type": "SPEAKER_PHOTO", "s3_uri": "s3://pe-meetings/micro/000090/speaker.jpg", "content_type": "image/jpeg", "speaker_id": 1, "speaker_shot_kind": "TITLE_GROUP"},
    {"asset_id": 305, "asset_type": "PANORAMA", "s3_uri": "s3://pe-meetings/micro/000090/panorama.jpg", "content_type": "image/jpeg"},
    {"asset_id": 306, "asset_type": "SIGNIN", "s3_uri": "s3://pe-meetings/micro/000090/signin.pdf", "content_type": "application/pdf"}
  ]
}
EOF
```

大讲堂完整请求示例见 [02-api-io-contract.md](02-api-io-contract.md)。

### 3.4 响应

**202 受理成功**

```json
{
  "request_id": "req-micro-000090-001",
  "job_id": 9001,
  "status": "ACCEPTED"
}
```

**400 参数错误**

```json
{
  "error": {
    "code": "SCHEMA_INVALID",
    "message": "meeting_subtype 在 project_type=MICRO 时必填",
    "retryable": false
  }
}
```

---

## 4. 接口 2：查询材料检查结果

| 项 | 内容 |
|----|------|
| 方法 / 路径 | `GET /v1/retail_meeting_checks/{request_id}` |
| 说明 | 查询进度或终态结果 |
| 成功 | `200 OK` |

### 4.1 路径参数 / Query

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| request_id | path | string | 提交时的 request_id |
| mode | query | string | 响应模式：`simple`（**默认**）\| `full`。覆盖提交时 `options.response_mode` |

### 4.2 响应模式：`simple` vs `full`

| | **simple**（给 PE / 业务系统） | **full**（给 AI 开发 debug） |
|--|-------------------------------|------------------------------|
| 目的 | 页面展示：整场结论 + **哪张不合格 + 为什么** | 纠错排障：检测点全量、OCR、证据、中间步骤等，**越细越好** |
| 谁用 | PE 轮询 / 回调 / 前端列表 | AI 同学查问题；勿默认推给业务 UI |
| 体积 | 小 | 大 |
| 默认 | **是**（查询与回调默认 simple） | 显式 `?mode=full` 或 `options.response_mode=full` |

**约定：**

1. 服务端始终算完整结果并落库；`mode` 只影响**本次返回裁剪**，不改变判定。  
2. 回调默认 `simple`（除非提交时 `options.response_mode=full`）。  
3. 响应顶层带 `response_mode`，便于调用方确认。  
4. 检测点全表、主题查重见 [检测点清单与asset_results.md](检测点清单与asset_results.md)。

### 4.3 请求示例

```bash
# PE：默认 simple
curl -X GET 'https://retail-meeting-check-test.example.com/v1/retail_meeting_checks/req-micro-000090-001' \
  -H 'Authorization: Bearer YOUR_API_TOKEN'

# AI debug：full
curl -X GET 'https://retail-meeting-check-test.example.com/v1/retail_meeting_checks/req-micro-000090-001?mode=full' \
  -H 'Authorization: Bearer YOUR_API_TOKEN'
```

### 4.4 响应：进行中（两种 mode 相同骨架）

```json
{
  "response_mode": "simple",
  "request_id": "req-micro-000090-001",
  "meeting_id": 1090,
  "job_id": 9001,
  "overall_status": null,
  "processing_status": "RUNNING",
  "message": "检查进行中",
  "asset_results": [],
  "rule_results": []
}
```

继续轮询，直到 `overall_status` 为 `PASS` / `FAIL` / `NEED_HUMAN` / `ERROR`。

### 4.5 公共顶层字段（simple / full 都有）

| 字段 | 类型 | 说明 |
|------|------|------|
| response_mode | string | `simple` \| `full` |
| request_id | string | 请求 ID |
| meeting_id | integer | 会议 ID |
| job_id | integer | 任务 ID |
| attempt_no | integer | 本场第几次检查 |
| overall_status | string | `PASS` \| `FAIL` \| `NEED_HUMAN` \| `ERROR` |
| summary_matched | string[] | 通过要点（展示用） |
| summary_failed | string[] | 整场不通过原因（展示用） |
| need_human_reasons | string[] | 待人工原因 |
| error | object/null | 仅 ERROR：`code` / `message` / `retryable` |
| asset_results | array | 每张材料一条（字段随 mode 增减） |
| rule_results | array | 场级规则（字段随 mode 增减） |
| finished_at | string | ISO-8601 |

**PE 状态映射**

| overall_status | PE 会议状态 |
|----------------|-------------|
| PASS | 通过 |
| FAIL | 不通过（可改材料后换新 request_id 重提） |
| NEED_HUMAN | 待人工（不要当成 FAIL） |
| ERROR | 保持待校验并告警重试（不要记业务不合格） |

### 4.6 `simple` 模式（系统展示必须）

核心问题：**哪张照片不合格？不合格原因是什么？**

**asset_results[]（simple）**

| 字段 | 类型 | 说明 |
|------|------|------|
| asset_id | int | 材料 ID |
| declared_type | string | PE 声明类型 |
| asset_status | string | `PASS` \| `FAIL` \| `UNCERTAIN` \| `ERROR` |
| fail_reasons | array | **不合格/待人工原因列表**；通过时为 `[]` |

**fail_reasons[]**

| 字段 | 说明 |
|------|------|
| check | 检测点名（如 `name_set_matches_speakers`）；场级问题也可空或用规则码 |
| reason_code | 机器可读原因码 |
| reason_text | **给用户看的中文原因**（PE 直接展示） |

**rule_results[]（simple）**

| 字段 | 说明 |
|------|------|
| rule_code | 规则码 |
| passed | bool/null |
| status | `PASS` \| `FAIL` \| `SKIP` \| `UNCERTAIN` |
| reason_code / reason_text | 原因 |
| related_asset_ids | 关联材料（方便点到具体照片） |

> simple **不返回**：完整 `checks` 字典、OCR 原文、检测框、`evidence`、清晰度分数、`debug` 等。

**simple · FAIL 示例（PE 最常用）**

```json
{
  "response_mode": "simple",
  "request_id": "req-hall-x-002",
  "meeting_id": 1009,
  "job_id": 9002,
  "overall_status": "FAIL",
  "summary_matched": ["拜耳Logo检出"],
  "summary_failed": ["台卡缺少讲者「刘亭」", "全景合计人数28<35"],
  "need_human_reasons": [],
  "error": null,
  "asset_results": [
    {
      "asset_id": 201,
      "declared_type": "POSTER",
      "asset_status": "PASS",
      "fail_reasons": []
    },
    {
      "asset_id": 203,
      "declared_type": "NAME_CARD",
      "asset_status": "FAIL",
      "fail_reasons": [
        {
          "check": "name_set_matches_speakers",
          "reason_code": "NAME_SET_MISMATCH",
          "reason_text": "台卡缺少讲者「刘亭」"
        }
      ]
    },
    {
      "asset_id": 210,
      "declared_type": "PANORAMA",
      "asset_status": "FAIL",
      "fail_reasons": [
        {
          "check": "people_count_recorded",
          "reason_code": "PANORAMA_BELOW_THRESHOLD",
          "reason_text": "本张计入全景后合计人数28，低于35人要求"
        }
      ]
    }
  ],
  "rule_results": [
    {
      "rule_code": "NAME_CARD_SPEAKER_MATCH",
      "passed": false,
      "status": "FAIL",
      "reason_code": "NAME_SET_MISMATCH",
      "reason_text": "台卡姓名集合与系统讲者不一致：缺少刘亭",
      "related_asset_ids": [203]
    },
    {
      "rule_code": "PANORAMA_COUNT",
      "passed": false,
      "status": "FAIL",
      "reason_code": "BELOW_THRESHOLD",
      "reason_text": "全景合计人数28<35",
      "related_asset_ids": [210]
    }
  ],
  "finished_at": "2026-04-18T11:00:00+08:00"
}
```

**simple · PASS 示例（节选）**

```json
{
  "response_mode": "simple",
  "request_id": "req-hall-2-20260417-001",
  "meeting_id": 1002,
  "job_id": 9001,
  "overall_status": "PASS",
  "summary_matched": ["日程海报与表单一致", "台卡四名一致", "拜耳Logo检出"],
  "summary_failed": [],
  "need_human_reasons": [],
  "error": null,
  "asset_results": [
    { "asset_id": 201, "declared_type": "POSTER", "asset_status": "PASS", "fail_reasons": [] },
    { "asset_id": 203, "declared_type": "NAME_CARD", "asset_status": "PASS", "fail_reasons": [] }
  ],
  "rule_results": [
    {
      "rule_code": "NAME_CARD_SPEAKER_MATCH",
      "passed": true,
      "status": "PASS",
      "reason_text": "台卡姓名与系统讲者一致",
      "related_asset_ids": [203]
    }
  ],
  "finished_at": "2026-04-18T10:00:00+08:00"
}
```

### 4.7 `full` 模式（AI debug，字段尽量全）

在 **simple 全部字段**之上，再返回（或补全）以下内容；`asset_results` / `rule_results` 用完整结构。

**额外顶层**

| 字段 | 说明 |
|------|------|
| overall_confidence | 0~1 |
| model_version / template_pack_version | 模型与模版包版本 |
| debug | 排障对象（见下） |

**debug（建议）**

| 字段 | 说明 |
|------|------|
| pipeline_steps | 各步骤名、耗时 ms、成功/失败、错误信息 |
| artifact_refs | 可继续查库/S3 的中间产物引用（`ai_step_log` / `ai_artifact`） |
| notes | 任意补充说明 |

**asset_results[]（full = simple + 下列）**

| 字段 | 类型 | 说明 |
|------|------|------|
| （含 simple 的 asset_status / fail_reasons） | | 方便同一套解析 |
| detected_type / type_match | | 类型识别 |
| clarity_score / is_clear | | 清晰度 |
| checks | object | **全部检测点** true/false/null |
| uncertain_checks | string[] | 拿不准的点 |
| ocr_fields | object/null | 结构化抽取（日期/地点/姓名等） |
| ocr_raw | string/null | OCR 原文（纠错用） |
| detections | object/null | 框、人数点、Logo ROI 等 |
| image_dup_hit | bool | 本张是否与**其他会议**照片重复（跨会议混用） |
| image_dup_kind | string/null | `exact` \| `similar` |
| image_dup_score | float/null | 近似相似度 |
| image_dup_ref_session_no / image_dup_ref_meeting_id | | 撞到的历史场次/会议 |
| topic_reuse_hit | bool | **讲者照**标题是否撞历史 |
| topic_reuse_ref_session_no | string/null | 撞到的历史场次 |
| topic_text_ocr | string/null | 讲者照 OCR 标题 |
| model_scores | object/null | 各子模型分数 |
| fetch_error | object/null | 下载失败详情 |

**`checks` 命名：** 正向语义。`has_bayer_logo: true` = 有 Logo。不适用 → `null`。  
常用：`type_match` · `is_clear` · `image_not_duplicated` · `has_bayer_logo` · `date_matches_form` · `topic_matches_form` · `topic_not_reused_in_period` · `name_set_matches_speakers` · `handbook_detected` · `ppt_template_match` …

**rule_results[]（full）** 在 simple 基础上增加：`confidence` · `trigger_human` · `evidence`（比对明细、阈值、中间计数等）。

**两类查重（勿混）：**  
- **主题/标题重复**（`TOPIC_REUSE`）：OCR 标题 → 归一化 → 历史字符串比（**仅讲者照**）。  
- **照片重复/盗用他场**（`IMAGE_DUP`）：pHash/embedding 与**其他会议**比（本场全部照片；**不查会内**相似）。

**full · FAIL 示例（节选一张台卡）**

```json
{
  "response_mode": "full",
  "request_id": "req-hall-x-002",
  "meeting_id": 1009,
  "job_id": 9002,
  "overall_status": "FAIL",
  "overall_confidence": 0.88,
  "model_version": "rmc-vision-2026.10.1",
  "template_pack_version": "2026Q2",
  "summary_matched": ["拜耳Logo检出"],
  "summary_failed": ["台卡缺少讲者「刘亭」"],
  "need_human_reasons": [],
  "error": null,
  "asset_results": [
    {
      "asset_id": 203,
      "declared_type": "NAME_CARD",
      "asset_status": "FAIL",
      "fail_reasons": [
        {
          "check": "name_set_matches_speakers",
          "reason_code": "NAME_SET_MISMATCH",
          "reason_text": "台卡缺少讲者「刘亭」"
        }
      ],
      "detected_type": "NAME_CARD",
      "type_match": true,
      "clarity_score": 0.86,
      "is_clear": true,
      "checks": {
        "type_match": true,
        "is_clear": true,
        "name_card_count_ok": false,
        "name_set_matches_speakers": false
      },
      "uncertain_checks": [],
      "ocr_fields": {
        "speaker_names": ["余艳红", "袁芳", "高芳"]
      },
      "ocr_raw": "余艳红\n袁芳\n高芳",
      "detections": {
        "name_card_rois": [[120, 80, 400, 220], [420, 80, 700, 220], [720, 80, 1000, 220]]
      },
      "model_scores": { "name_ocr_avg": 0.91 }
    }
  ],
  "rule_results": [
    {
      "rule_code": "NAME_CARD_SPEAKER_MATCH",
      "passed": false,
      "status": "FAIL",
      "confidence": 0.92,
      "trigger_human": false,
      "reason_code": "NAME_SET_MISMATCH",
      "reason_text": "台卡姓名集合与系统讲者不一致：缺少刘亭",
      "evidence": {
        "names_ocr": ["余艳红", "袁芳", "高芳"],
        "names_form": ["余艳红", "刘亭", "袁芳", "高芳"],
        "missing": ["刘亭"],
        "extra": []
      },
      "related_asset_ids": [203]
    }
  ],
  "debug": {
    "pipeline_steps": [
      { "step": "download", "ms": 180, "ok": true },
      { "step": "clarity", "ms": 40, "ok": true },
      { "step": "name_card_ocr", "ms": 620, "ok": true }
    ],
    "artifact_refs": { "job_id": 9002, "tables": ["ai_step_log", "ai_artifact"] }
  },
  "finished_at": "2026-04-18T11:00:00+08:00"
}
```

### 4.8 其他终态（simple 即可；full 同结构加详字段）

**NEED_HUMAN**

```json
{
  "response_mode": "simple",
  "request_id": "req-micro-y-003",
  "meeting_id": 1100,
  "job_id": 9003,
  "overall_status": "NEED_HUMAN",
  "summary_matched": [],
  "summary_failed": [],
  "need_human_reasons": ["签到表模糊，无法可靠读取起止时间"],
  "error": null,
  "asset_results": [
    {
      "asset_id": 401,
      "declared_type": "SIGNIN",
      "asset_status": "UNCERTAIN",
      "fail_reasons": [
        {
          "check": "duration_readable",
          "reason_code": "BLURRY",
          "reason_text": "签到表模糊，无法可靠读取起止时间"
        }
      ]
    }
  ],
  "rule_results": [
    {
      "rule_code": "SIGNIN_DURATION",
      "passed": null,
      "status": "UNCERTAIN",
      "reason_code": "BLURRY",
      "reason_text": "签到表模糊，无法可靠读取起止时间",
      "related_asset_ids": [401]
    }
  ],
  "finished_at": "2026-05-28T09:00:00+08:00"
}
```

**ERROR**

```json
{
  "response_mode": "simple",
  "request_id": "req-micro-z-004",
  "meeting_id": 1101,
  "job_id": 9004,
  "overall_status": "ERROR",
  "summary_matched": [],
  "summary_failed": [],
  "need_human_reasons": [],
  "error": {
    "code": "S3_NOT_FOUND",
    "message": "对象不存在: s3://pe-meetings/micro/1101/poster.jpg",
    "retryable": false
  },
  "asset_results": [
    {
      "asset_id": 501,
      "declared_type": "E_POSTER",
      "asset_status": "ERROR",
      "fail_reasons": [
        {
          "check": null,
          "reason_code": "S3_NOT_FOUND",
          "reason_text": "材料下载失败，对象不存在"
        }
      ]
    }
  ],
  "rule_results": [],
  "finished_at": "2026-05-28T09:05:00+08:00"
}
```

### 4.9 404

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "request_id 不存在",
    "retryable": false
  }
}
```

---

## 5. 接口 3：审核完成回调（PE 提供）

| 项 | 内容 |
|----|------|
| 方法 / 路径 | `POST {X-Callback-URL}`（PE 自己的地址） |
| 说明 | AI 审核结束后主动推送结果；**可选** |
| 触发条件 | 提交接口 1 时带了 `X-Callback-URL` |
| PE 成功响应 | HTTP `2xx`（建议 5s 内） |

### 5.1 请求头（AI → PE）

| Header | 说明 |
|--------|------|
| Content-Type | `application/json` |
| X-Request-Id | 对应 `request_id` |
| X-Signature | `sha256=` + HMAC-SHA256(原始 Body，双方约定密钥) 的小写 hex |

### 5.2 请求体

与接口 2 的**终态**相同；默认 **`simple`**（除非提交时 `options.response_mode=full`）。字段见 §4.5～4.8。

### 5.3 PE 侧要求

- 同一 `request_id` 可能收到重复回调 → **幂等处理**
- 非 2xx 时 AI 最多重试 3 次（指数退避）
- 未配置回调时，仅用接口 2 轮询
- PE 展示页按 **simple** 解析即可：看 `asset_results[].asset_status` + `fail_reasons`

---

## 6. 接口 4：健康检查

| 项 | 内容 |
|----|------|
| 方法 / 路径 | `GET /health` |
| 说明 | 探测服务是否可用 |
| 成功 | `200 OK` |

```bash
curl -X GET 'https://retail-meeting-check-test.example.com/health' \
  -H 'Authorization: Bearer YOUR_API_TOKEN'
```

```json
{
  "status": "ok"
}
```

---

## 7. 错误码

### 7.1 HTTP

| HTTP | 含义 |
|------|------|
| 200 | 查询成功 / 健康检查成功 |
| 202 | 提交已受理 |
| 400 | 参数非法 |
| 401 | 未鉴权 |
| 403 | 无权限 |
| 404 | request_id 不存在 |
| 429 | 限流 |
| 500 | 内部错误 |
| 503 | 依赖不可用 |

### 7.2 error.code（系统）

| code | 可重试 | 说明 |
|------|--------|------|
| UNAUTHORIZED | N | 鉴权失败 |
| FORBIDDEN | N | 无权限 |
| SCHEMA_INVALID | N | 字段不合规 |
| NOT_FOUND | N | 无此 request_id |
| S3_NOT_FOUND | N | 对象不存在 |
| S3_ACCESS_DENIED | N | 无读权限 |
| S3_TIMEOUT | Y | 拉取超时 |
| S3_CORRUPT | N | 无法解码 |
| ASSET_MISSING | N | URI 无效 |
| MODEL_TIMEOUT | Y | 推理超时 |
| MODEL_UNAVAILABLE | Y | 模型不可用 |
| TEMPLATE_PACK_NOT_FOUND | N | 模版版本不存在 |
| RATE_LIMITED | Y | 限流 |
| INTERNAL_ERROR | Y | 未知错误 |

### 7.3 reason_code（业务规则，摘要）

| reason_code | 说明 |
|-------------|------|
| BLURRY | 清晰度不足 |
| TYPE_MISMATCH | 类别不符 |
| FIELD_MISMATCH | 与表单不一致 |
| LOGO_MISSING | 无拜耳 Logo |
| COUNT_BELOW_THRESHOLD | 人数不足 |
| DURATION_BELOW_THRESHOLD | 时长不足 |
| IMAGE_DUP | 盗用/混用其他会议现场照（pHash/embedding，跨会议） |
| TOPIC_REUSED | 讲者照主题/标题与历史会议重复 |
| NAME_SET_MISMATCH | 台卡姓名不匹配 |
| HANDBOOK_NOT_FOUND / HANDBOOK_STALE | 手册未识别 / 旧版 |
| TEMPLATE_MISMATCH | 模版不一致 |
| TOPIC_MISMATCH | 主题不一致 |
| OCR_LOW_CONFIDENCE | OCR 置信度低 |

规则明细见 [03-rule-matrix.md](03-rule-matrix.md)。

---

## 8. 附录：对接检查清单

- [ ] 测试/生产 Base URL、Token 已配置  
- [ ] S3 可读；`s3_uri` 正确  
- [ ] 接口 1 提交 + 接口 2 轮询（和/或接口 3 回调）已联调  
- [ ] `asset_type` 与实际上传一致；必传材料已齐  
- [ ] 四种 `overall_status` 已映射；`ERROR` ≠ `FAIL`  
- [ ] 重提使用新 `request_id`  
