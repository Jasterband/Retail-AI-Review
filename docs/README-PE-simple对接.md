# 零售会议材料检查 · PE 对接说明（simple 模式）

| 项 | 内容 |
|----|------|
| 适用对象 | **PE / 业务系统开发**（页面展示、状态写回） |
| 响应模式 | **`simple`（默认）** |
| 文档用途 | 联调与对接：如何提交、如何轮询/回调、如何解析「哪张不合格 + 为什么」 |
| 完整契约 | 字段全集、full 排障字段见 [PE接口文档-v1.8.md](PE接口文档-v1.8.md) |
| OpenAPI | [openapi/pe-retail-meeting-check.v1.yaml](openapi/pe-retail-meeting-check.v1.yaml) |

> **请勿**在业务 UI 默认使用 `mode=full`。full 仅供 AI 排障（OCR、检测框、debug 等），体积大且字段会变。

---

## 1. 你需要实现什么

```text
1. 材料上传到 S3（PE 写）
2. POST /v1/retail_meeting_checks          → 202，拿到 request_id / job_id
3. 轮询 GET .../{request_id}（默认 simple）
   和/或 等待 AI 回调（提交时带 X-Callback-URL）
4. 按 overall_status 写回会议状态
5. 列表/详情页：展示 summary_* + 每张图的 asset_status / fail_reasons
```

**AI 侧：** 只读 S3、做材料检查、返回结构化结果。  
**PE 自理：** 讲者次数、主题业务规则、表单时长等（不由本接口判定）。

---

## 2. 公共约定

### 2.1 Base URL / 鉴权

| 环境 | Base URL（上线前替换） |
|------|------------------------|
| 测试 | `https://retail-meeting-check-test.example.com` |
| 生产 | `https://retail-meeting-check.example.com` |

```http
Authorization: Bearer <YOUR_API_TOKEN>
Content-Type: application/json
```

未带或无效 Token → `401`；无权限 → `403`。

### 2.2 通用规则

| 项 | 约定 |
|----|------|
| 协议 | HTTPS，JSON，UTF-8 |
| 材料 | **只传 `s3_uri`**，不传文件二进制；AI 需有桶只读权限 |
| 幂等 | 相同 `request_id` 不重复计次，返回首次结果 |
| 重提 | 用户改材料后再审 → **必须换新** `request_id` |
| 轮询 | 建议首次 3s，之后每 5s，最长约 10 分钟 |
| 限流 | 默认 60 次/分钟/Token，超限 `429` |

### 2.3 接口清单

| 序号 | 方向 | 方法 | 路径 | 成功码 |
|------|------|------|------|--------|
| 1 | PE → AI | `POST` | `/v1/retail_meeting_checks` | `202` |
| 2 | PE → AI | `GET` | `/v1/retail_meeting_checks/{request_id}` | `200` |
| 3 | AI → PE | `POST` | `{X-Callback-URL}` | PE 回 `2xx` |
| 4 | PE → AI | `GET` | `/health` | `200` |

---

## 3. 提交检查

`POST /v1/retail_meeting_checks`

### 3.1 请求头

| Header | 必填 | 说明 |
|--------|------|------|
| Authorization | 是 | `Bearer <token>` |
| Content-Type | 是 | `application/json` |
| X-Callback-URL | 否 | 完成后回调的 HTTPS 地址；不传则只靠轮询 |
| Idempotency-Key | 否 | 若传须与 `request_id` 一致 |

### 3.2 请求体（必填摘要）

| 字段 | 说明 |
|------|------|
| `request_id` | 唯一 ID，8~64 字符 |
| `meeting_id` | PE 会议主键 |
| `session_no` | 场次编号 |
| `project_type` | `LECTURE_HALL` \| `MICRO` |
| `meeting_subtype` | 微型必填 `SINGLE`\|`DUAL`；大讲堂传 `null` |
| `period_id` | 项目期数 ID |
| `form` | 会议表单（日期、时间、地点、人数、讲者等） |
| `assets[]` | 材料列表（`asset_id` / `asset_type` / `s3_uri` / `content_type`） |

**可选：** `refs`（模版包、查重范围）、`options`（阈值等）。  
回调默认模式：`options.response_mode`，默认即为 **`simple`**。

**大讲堂常用 `asset_type`：** `E_POSTER` · `POSTER` · `STAND` · `NAME_CARD` · `HANDBOOK` · `SPEAKER_PHOTO` · `PANORAMA` · `SIGNIN`  
**微型常用 `asset_type`：** `E_POSTER` · `E_POSTER_DISPLAY` · `PROJECT_INTRO_DISPLAY` · `SPEAKER_PHOTO` · `PANORAMA` · `SIGNIN`  

讲者照需带 `speaker_id`；`speaker_shot_kind` 为 `TITLE_GROUP` \| `LECTURING`。

字段全集与校验细则见 [PE接口文档-v1.8.md](PE接口文档-v1.8.md) §3。

### 3.3 请求示例（微型）

```bash
curl -X POST 'https://retail-meeting-check-test.example.com/v1/retail_meeting_checks' \
  -H 'Authorization: Bearer YOUR_API_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
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
      {"asset_id": 302, "asset_type": "PROJECT_INTRO_DISPLAY", "s3_uri": "s3://pe-meetings/micro/000090/display1.jpg", "content_type": "image/jpeg"},
      {"asset_id": 303, "asset_type": "E_POSTER_DISPLAY", "s3_uri": "s3://pe-meetings/micro/000090/intro.jpg", "content_type": "image/jpeg"},
      {"asset_id": 304, "asset_type": "SPEAKER_PHOTO", "s3_uri": "s3://pe-meetings/micro/000090/speaker.jpg", "content_type": "image/jpeg", "speaker_id": 1, "speaker_shot_kind": "TITLE_GROUP"},
      {"asset_id": 305, "asset_type": "PANORAMA", "s3_uri": "s3://pe-meetings/micro/000090/panorama.jpg", "content_type": "image/jpeg"},
      {"asset_id": 306, "asset_type": "SIGNIN", "s3_uri": "s3://pe-meetings/micro/000090/signin.pdf", "content_type": "application/pdf"}
    ]
  }'
```

### 3.4 受理响应 `202`

```json
{
  "request_id": "req-micro-000090-001",
  "job_id": 9001,
  "status": "ACCEPTED"
}
```

参数错误 → `400`，例如：

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

## 4. 查询结果（simple）

`GET /v1/retail_meeting_checks/{request_id}`

| 参数 | 说明 |
|------|------|
| `request_id` | path，提交时的 ID |
| `mode` | query，**默认 `simple`**；业务侧不要传 `full` |

```bash
# 推荐：省略 mode，即为 simple
curl -X GET 'https://retail-meeting-check-test.example.com/v1/retail_meeting_checks/req-micro-000090-001' \
  -H 'Authorization: Bearer YOUR_API_TOKEN'
```

### 4.1 进行中

`overall_status` 为 `null`，继续轮询：

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

终态：`overall_status` ∈ `PASS` \| `FAIL` \| `NEED_HUMAN` \| `ERROR`。

---

## 5. simple 终态响应（对接核心）

### 5.1 页面要回答的问题

1. **整场结论是什么？** → `overall_status` + `summary_matched` / `summary_failed` / `need_human_reasons`  
2. **哪张不合格？** → `asset_results[].asset_status`  
3. **为什么？** → `asset_results[].fail_reasons[].reason_text`（可直接展示给用户）

### 5.2 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `response_mode` | string | 固定为 `"simple"`（确认未误用 full） |
| `request_id` | string | 请求 ID |
| `meeting_id` | integer | 会议 ID |
| `job_id` | integer | 任务 ID |
| `attempt_no` | integer | 本场第几次检查（若返回） |
| `overall_status` | string | `PASS` \| `FAIL` \| `NEED_HUMAN` \| `ERROR` |
| `summary_matched` | string[] | 通过要点（展示用） |
| `summary_failed` | string[] | 整场不通过原因（展示用） |
| `need_human_reasons` | string[] | 待人工原因 |
| `error` | object/null | 仅 `ERROR`：`code` / `message` / `retryable` |
| `asset_results` | array | 每张材料一条 |
| `rule_results` | array | 场级规则摘要 |
| `finished_at` | string | ISO-8601 |

**simple 不返回：** `checks`、OCR 原文、检测框、`evidence`、清晰度分数、`overall_confidence`、`model_version`、`debug` 等。

### 5.3 `asset_results[]`

| 字段 | 类型 | 说明 |
|------|------|------|
| `asset_id` | int | 材料 ID（与提交一致） |
| `declared_type` | string | PE 声明的 `asset_type` |
| `asset_status` | string | `PASS` \| `FAIL` \| `UNCERTAIN` \| `ERROR` |
| `fail_reasons` | array | 原因列表；通过时为 `[]` |

**`fail_reasons[]`**

| 字段 | 说明 |
|------|------|
| `check` | 检测点名（可空） |
| `reason_code` | 机器可读码（可做 i18n / 埋点） |
| `reason_text` | **给用户看的中文**（优先直接展示） |

### 5.4 `rule_results[]`

| 字段 | 说明 |
|------|------|
| `rule_code` | 规则码 |
| `passed` | bool / null |
| `status` | `PASS` \| `FAIL` \| `SKIP` \| `UNCERTAIN` |
| `reason_code` / `reason_text` | 原因 |
| `related_asset_ids` | 关联材料，便于点到具体照片 |

### 5.5 会议状态映射（务必区分）

| `overall_status` | PE 建议处理 |
|------------------|-------------|
| `PASS` | 标记通过 |
| `FAIL` | 标记不通过；用户可改材料后 **换新 `request_id`** 重提 |
| `NEED_HUMAN` | **待人工**，不要当成 FAIL |
| `ERROR` | **系统错误**：保持待校验并告警重试；**不要**记业务不合格 |

---

## 6. 响应示例

### 6.1 FAIL（最常用）

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

**前端建议：**

- 顶部：根据 `overall_status` 显示结论 + 列出 `summary_failed`
- 材料列表：按 `asset_id` 对齐缩略图；`FAIL`/`UNCERTAIN` 高亮，下方渲染 `fail_reasons[].reason_text`
- 可选：用 `rule_results[].related_asset_ids` 做「规则 → 照片」跳转

### 6.2 PASS（节选）

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

### 6.3 NEED_HUMAN

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

展示 `need_human_reasons`（及对应材料的 `fail_reasons`），走人工审核流，**不要**按业务 FAIL 处理。

### 6.4 ERROR

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

看 `error.retryable`：可重试则告警后用**同一或新**策略重提；不可重试则修数据（如 S3 路径）后再提。**不要**写成业务不合格。

---

## 7. 回调（可选）

提交时带 `X-Callback-URL`，审核结束后 AI 向该地址 `POST` **终态 simple 结果**（结构与 §5 / §6 相同）。

| Header | 说明 |
|--------|------|
| `Content-Type` | `application/json` |
| `X-Request-Id` | 对应 `request_id` |
| `X-Signature` | `sha256=` + HMAC-SHA256(原始 Body，双方约定密钥) 的小写 hex |

PE 侧要求：

- 5s 内返回 HTTP `2xx`
- 同一 `request_id` **幂等**（可能重复推送）
- 非 2xx 时 AI 最多重试 3 次（指数退避）
- 未配置回调时，仅用查询接口轮询

---

## 8. 健康检查

```bash
curl -X GET 'https://retail-meeting-check-test.example.com/health' \
  -H 'Authorization: Bearer YOUR_API_TOKEN'
```

```json
{ "status": "ok" }
```

---

## 9. 错误码速查

### HTTP

| HTTP | 含义 |
|------|------|
| 200 | 查询 / 健康检查成功 |
| 202 | 提交已受理 |
| 400 | 参数非法 |
| 401 / 403 | 鉴权失败 / 无权限 |
| 404 | `request_id` 不存在 |
| 429 | 限流 |
| 500 / 503 | 内部错误 / 依赖不可用 |

### `error.code`（系统，节选）

| code | 可重试 | 说明 |
|------|--------|------|
| `SCHEMA_INVALID` | N | 字段不合规 |
| `NOT_FOUND` | N | 无此 request_id |
| `S3_NOT_FOUND` / `S3_ACCESS_DENIED` | N | 对象不存在 / 无读权限 |
| `S3_TIMEOUT` | Y | 拉取超时 |
| `MODEL_TIMEOUT` / `MODEL_UNAVAILABLE` | Y | 推理超时 / 不可用 |
| `RATE_LIMITED` | Y | 限流 |
| `INTERNAL_ERROR` | Y | 未知错误 |

### `reason_code`（业务，节选）

| reason_code | 说明 |
|-------------|------|
| `BLURRY` | 清晰度不足 |
| `TYPE_MISMATCH` | 类别不符 |
| `FIELD_MISMATCH` | 与表单不一致 |
| `LOGO_MISSING` | 无拜耳 Logo |
| `COUNT_BELOW_THRESHOLD` | 人数不足 |
| `DURATION_BELOW_THRESHOLD` | 时长不足 |
| `IMAGE_DUP` | 盗用/混用其他会议现场照 |
| `TOPIC_REUSED` | 讲者照主题与历史重复 |
| `NAME_SET_MISMATCH` | 台卡姓名不匹配 |
| `HANDBOOK_NOT_FOUND` / `HANDBOOK_STALE` | 手册未识别 / 旧版 |
| `TEMPLATE_MISMATCH` | 模版不一致 |
| `OCR_LOW_CONFIDENCE` | OCR 置信度低 |

展示文案优先用 `reason_text`；`reason_code` 用于逻辑分支或统计。

---

## 10. 对接检查清单

- [ ] 测试/生产 Base URL、Bearer Token 已配置  
- [ ] S3 已上传且 AI 可读；`s3_uri` 格式正确  
- [ ] `POST` 提交 + `GET` 轮询（和/或回调）已联调  
- [ ] 业务 UI **只解析 simple**；确认响应里 `response_mode === "simple"`  
- [ ] 四种 `overall_status` 已映射；`NEED_HUMAN` ≠ `FAIL`；`ERROR` ≠ 业务不合格  
- [ ] 列表按 `asset_results` 展示不合格材料与 `reason_text`  
- [ ] 重提使用**新** `request_id`  
- [ ] 回调已做签名校验与幂等（若启用）  

---

## 11. 相关文档

| 文档 | 何时查阅 |
|------|----------|
| [PE接口文档-v1.8.md](PE接口文档-v1.8.md) | 完整字段、full 模式、规则细节 |
| [PPT字段名对照-第5-6页.md](PPT字段名对照-第5-6页.md) | PPT 中文列 ↔ API 字段名 |
| [02-api-io-contract.md](02-api-io-contract.md) | 大讲堂完整请求示例、聚合规则 |
| [schemas/retail-meeting-check-request.schema.json](schemas/retail-meeting-check-request.schema.json) | 请求 JSON Schema |
| [schemas/retail-meeting-check-response.schema.json](schemas/retail-meeting-check-response.schema.json) | 响应 JSON Schema |
