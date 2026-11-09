# 零售会议材料检查 · PE 对接说明

| 项 | 内容 |
|----|------|
| 适用对象 | **PE 后台**（接收 AI 结构化结果，自行后处理后再展示前端） |
| 文档用途 | 联调：如何提交、轮询/回调、如何解析结构化结论 |
| **契约权威** | **以本文为准**（simple 最瘦）；OpenAPI / v1.8 若与本文冲突，以本文为准 |
| OpenAPI | [openapi/pe-retail-meeting-check.v1.yaml](./openapi/pe-retail-meeting-check.v1.yaml)（可能滞后，仅作参考） |

> AI → PE 终态只给：`overall_status` + `photo_results`（+ 系统失败时的 `error`）。  
> 页面文案由 PE 根据 `fail_reasons[].reason_code` 自行组装。

---

## 1. PE 端需要实现什么

```text
1. 材料上传到 S3（PE 写）
2. POST /v1/retail_meeting_checks          → 202，拿到 task_id
3. 轮询 GET .../{task_id}
   和/或 等待 AI 回调（提交时带 X-Callback-URL）
4. 按 overall_status 写回会议状态
5. 用 photo_results 按图后处理，再渲染自有前端
```

**AI 端：** 只读 S3、做材料检查、返回按图结构化结果。  
**PE 端另需自理：** 讲者次数、主题业务规则、表单时长、**前端文案拼装**等。

---

## 2. 公共约定

### 2.1 联调就绪（上线前必须换成真值）

| 项 | 现状 / 约定 | PE 需要拿到什么 |
|----|-------------|-----------------|
| 测试 Base URL | `https://retail-meeting-check-test.example.com`（占位） | 真实测试域名 |
| 生产 Base URL | `https://retail-meeting-check.example.com`（占位） | 真实生产域名 |
| Bearer Token | 格式见下；**发放方式联调前由 AI 侧提供** | 测试/生产各一套 Token；轮换策略 |
| S3 | PE 写、AI 只读；只传 `file_url` | 桶名、路径规范、跨账号读权限是否已开 |
| 回调 HMAC 密钥 | 算法见 §7；**密钥线下交换** | 测试/生产各一把（可不同） |
| 联调联系 | 见 §12 | 缺陷/加码通知渠道 |

```http
Authorization: Bearer <YOUR_API_TOKEN>
Content-Type: application/json
```

未带 Token → `401` `UNAUTHORIZED`；无效 → `403` `FORBIDDEN`。

### 2.2 通用规则

| 项 | 约定 |
|----|------|
| 协议 | HTTPS，JSON，UTF-8 |
| 材料 | **只传 `file_url`**（`s3://bucket/key`），不传文件二进制 |
| `task_id` | **PE 生成**；长度 8~50；建议可读且唯一，如 `req-{project}-{meeting_no}-{yyyyMMddHHmmss}-{seq}` |
| 幂等 | 相同 `task_id` 再 POST → **不重复计次**，返回与首次相同的受理（仅 `task_id`） |
| 重提 | 用户改材料 / 改表单后再审 → **必须换新** `task_id`（沿用旧 ID 会一直拿到旧结果） |
| 轮询 | 建议首次等 3s，之后每 5s；**最长约 10 分钟** |
| 轮询超时 | 超过约 10 分钟仍 `overall_status=null`：PE 停轮询、标「检查超时/异常」、告警；**不要**写成业务 FAIL。可稍后再 GET 同 `task_id` 看是否已终态；若需重跑检查 → **新** `task_id` 再 POST |
| 限流 | 默认 60 次/分钟/Token；`429` 时退避重试（建议 30s 起，或按响应头若有 `Retry-After`） |
| `5xx` | 建议指数退避有限次重试；持续失败告警，勿改会议为业务不合格 |

### 2.3 接口清单

| 序号 | 方向 | 方法 | 路径 | 成功码 |
|------|------|------|------|--------|
| 1 | PE → AI | `POST` | `/v1/retail_meeting_checks` | `202` |
| 2 | PE → AI | `GET` | `/v1/retail_meeting_checks/{task_id}` | `200` |
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
| Idempotency-Key | 否 | 若传须与 `task_id` 一致 |

### 3.2 请求体

**本接口返回类型：**

| 时机 | HTTP | 说明 |
|------|------|------|
| 受理即时 | `202` | `AcceptedResponse`，见 §3.4 |
| 轮询 / 回调终态 | `200` / 回调 POST | 结构化检查结果，见 §4–§5 |

**顶层字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | `string` | 唯一 ID，8~50 字符（对齐 CRM `TaskID`） |
| `meeting_id` | `string` | PE/CRM 会议主键（≤36；对齐 `MeetingID` nvarchar，可为 GUID） |
| `meeting_no` | `string` | 场次编号，≤20 |
| `project_type` | `string` enum | `LECTURE_HALL` \| `MICRO` |
| `meeting_type` | `string` \| `null` | 微型必填 `SINGLE`\|`DUAL`；大讲堂必须 `null` |
| `project_id` | `string` | 项目期数 ID（≤36；对齐 `ProjectID` nvarchar） |
| `form` | `object` | 会议表单，见下表 |
| `photos` | `PhotoItem[]` | 材料列表，≥1；须覆盖必审类型 |
| `refs` | `object` \| 省略 | 可选，联调一般不传 |
| `options` | `object` \| 省略 | 可选，联调一般不传 |

**`form`（`MeetingForm`）**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `meeting_name` | `string` | 是 | ≤50 |
| `meeting_date` | `string` | 是 | 会议日期（如 `YYYY-MM-DD`） |
| `start_time` | `string` | 是 | 开始时间（如 `HH:MM`） |
| `end_time` | `string` | 是 | 结束时间 |
| `chain_or_store_name` | `string` | 是 | 连锁 / 门店名 |
| `meeting_location` | `string` | 是 | 地点 |
| `total_attendees` | `integer` | 是 | 参会总人数 |
| `speakers` | `Speaker[]` | 是 | ≥1 |
| `remark` | `string` | 否 | 备注 |

**`form.speakers[]`（`Speaker`）**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `speaker_id` | `string` | 是 | 与 `photos[].speaker_id` 对齐（≤36；CRM `SpeakerID`） |
| `speaker_name` | `string` | 是 | 讲者姓名 |
| `topic` | `string` | 是 | 主题 |
| `store_name` | `string` | 是 | 门店 |
| `service_minutes` | `integer` | 是 | 服务时长（分钟） |
| `identity_name` | `string` | 是 | 身份/职称（≤10；对齐 CRM NotNull） |
| `lecture_fee` | `number` | 是 | 讲课费（对齐 CRM NotNull） |
| `tax` | `number` | 是 | 税金（对齐 CRM NotNull） |

**`photos[]`（`PhotoItem`）**

| 字段 | 类型 | 说明 |
|------|------|------|
| `photo_id` | `string` | 材料 ID（≤36；对齐 CRM `PhotoID`） |
| `photo_type` | `string` enum | 见下方；须与 `project_type` 匹配，否则 `400` |
| `file_url` | `string` | 须以 `s3://` 开头 |
| `content_type` | `string` enum | `image/jpeg` \| `image/jpg` \| `image/png` \| `application/pdf` |
| `sort` | `integer` | 同类型多张顺序，≥1（对齐 CRM NotNull） |
| `speaker_id` | `string` \| 省略 | **`SpeakerTitle` / `SpeakerLecture` 必填** |

**允许的 `photo_type`（按项目；与 CRM `PhotoType` 同值）**

| 项目 | 可提交类型 |
|------|------------|
| 大讲堂 `LECTURE_HALL` | `EDM` · `Poster` · `Stand` · `TableCard` · `Manual` · `SpeakerTitle` · `SpeakerLecture` · `Panorama` · `SignSheet` |
| 微型 `MICRO` | `EDM` · `EDMDisplay` · `ProjectIntro` · `SpeakerTitle` · `Panorama` · `SignSheet` |

**必审材料（缺一类 → 业务 `FAIL`，`reason_code=ASSET_MISSING`）**

| 项目 | 必审 `photo_type`（每类至少 1 份可读） |
|------|----------------------------------------|
| 大讲堂 | `EDM` · `Poster` · `Stand` · `TableCard` · `Manual` · `SpeakerTitle` · `SpeakerLecture` · `Panorama` · `SignSheet` |
| 微型 | `EDM` · `EDMDisplay` · `ProjectIntro` · `SpeakerTitle` · `Panorama` · `SignSheet` |

补充：大讲堂讲者照还须满足成对规则（`SpeakerTitle` + `SpeakerLecture`，按讲者），缺对亦会失败。

阈值、模版包等更深参数见 [PE接口文档-v1.8.md](PE接口文档-v1.8.md) / [schemas/retail-meeting-check-request.schema.json](schemas/retail-meeting-check-request.schema.json)。

### 3.3 请求示例

#### 微型 `MICRO` + `SINGLE`

```bash
curl -X POST 'https://retail-meeting-check-test.example.com/v1/retail_meeting_checks' \
  -H 'Authorization: Bearer YOUR_API_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "req-micro-000090-001",
    "meeting_id": "1090",
    "meeting_no": "000090",
    "project_type": "MICRO",
    "meeting_type": "SINGLE",
    "project_id": "2",
    "form": {
      "meeting_name": "单讲师",
      "meeting_date": "2026-05-27",
      "start_time": "14:00",
      "end_time": "14:35",
      "chain_or_store_name": "老百姓大药房连锁（安徽）有限公司",
      "meeting_location": "合肥市老百姓大药房连锁（安徽）有限公司淠河路店",
      "total_attendees": 7,
      "speakers": [
        {
          "speaker_id": "1",
          "speaker_name": "示例讲者",
          "topic": "慢病管理",
          "store_name": "淠河路店",
          "service_minutes": 30,
          "identity_name": "药师",
          "lecture_fee": 0,
          "tax": 0
        }
      ]
    },
    "photos": [
      {"photo_id": "301", "photo_type": "EDM", "file_url": "s3://pe-meetings/micro/000090/agenda.png", "content_type": "image/png", "sort": 1},
      {"photo_id": "302", "photo_type": "ProjectIntro", "file_url": "s3://pe-meetings/micro/000090/display1.jpg", "content_type": "image/jpeg", "sort": 2},
      {"photo_id": "303", "photo_type": "EDMDisplay", "file_url": "s3://pe-meetings/micro/000090/intro.jpg", "content_type": "image/jpeg", "sort": 3},
      {"photo_id": "304", "photo_type": "SpeakerTitle", "file_url": "s3://pe-meetings/micro/000090/speaker.jpg", "content_type": "image/jpeg", "sort": 4, "speaker_id": "1"},
      {"photo_id": "305", "photo_type": "Panorama", "file_url": "s3://pe-meetings/micro/000090/panorama.jpg", "content_type": "image/jpeg", "sort": 5},
      {"photo_id": "306", "photo_type": "SignSheet", "file_url": "s3://pe-meetings/micro/000090/signin.pdf", "content_type": "application/pdf", "sort": 6}
    ]
  }'
```

#### 大讲堂 `LECTURE_HALL`（`meeting_type` 必须 `null` / 省略）

```bash
curl -X POST 'https://retail-meeting-check-test.example.com/v1/retail_meeting_checks' \
  -H 'Authorization: Bearer YOUR_API_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "req-hall-1002-202604171000-01",
    "meeting_id": "1002",
    "meeting_no": "H1002",
    "project_type": "LECTURE_HALL",
    "meeting_type": null,
    "project_id": "2",
    "form": {
      "meeting_name": "美瑞大讲堂示例",
      "meeting_date": "2026-04-17",
      "start_time": "09:00",
      "end_time": "11:30",
      "chain_or_store_name": "示例连锁",
      "meeting_location": "成都市示例会议室",
      "total_attendees": 40,
      "speakers": [
        {
          "speaker_id": "1",
          "speaker_name": "张三",
          "topic": "慢病管理新进展",
          "store_name": "示例店",
          "service_minutes": 90,
          "identity_name": "药师",
          "lecture_fee": 0,
          "tax": 0
        }
      ]
    },
    "photos": [
      {"photo_id": "201", "photo_type": "EDM", "file_url": "s3://pe-meetings/hall/1002/e_poster.jpg", "content_type": "image/jpeg", "sort": 1},
      {"photo_id": "202", "photo_type": "Poster", "file_url": "s3://pe-meetings/hall/1002/poster.jpg", "content_type": "image/jpeg", "sort": 2},
      {"photo_id": "203", "photo_type": "Stand", "file_url": "s3://pe-meetings/hall/1002/stand.jpg", "content_type": "image/jpeg", "sort": 3},
      {"photo_id": "204", "photo_type": "TableCard", "file_url": "s3://pe-meetings/hall/1002/namecard.jpg", "content_type": "image/jpeg", "sort": 4},
      {"photo_id": "205", "photo_type": "Manual", "file_url": "s3://pe-meetings/hall/1002/handbook.jpg", "content_type": "image/jpeg", "sort": 5},
      {"photo_id": "206", "photo_type": "SpeakerTitle", "file_url": "s3://pe-meetings/hall/1002/speaker_title.jpg", "content_type": "image/jpeg", "sort": 6, "speaker_id": "1"},
      {"photo_id": "207", "photo_type": "SpeakerLecture", "file_url": "s3://pe-meetings/hall/1002/speaker_lecturing.jpg", "content_type": "image/jpeg", "sort": 7, "speaker_id": "1"},
      {"photo_id": "208", "photo_type": "Panorama", "file_url": "s3://pe-meetings/hall/1002/panorama.jpg", "content_type": "image/jpeg", "sort": 8},
      {"photo_id": "209", "photo_type": "SignSheet", "file_url": "s3://pe-meetings/hall/1002/signin.pdf", "content_type": "application/pdf", "sort": 9}
    ]
  }'
```

### 3.4 受理响应 `202`（`AcceptedResponse`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | `string` | 与请求一致；后续轮询 / 回调对齐用此 ID |

```json
{
  "task_id": "req-micro-000090-001"
}
```

参数错误 → `400`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `error.code` | `string` | 如 `SCHEMA_INVALID` |
| `error.message` | `string` | 可读错误说明 |
| `error.retryable` | `boolean` | 是否可直接重试 |

```json
{
  "error": {
    "code": "SCHEMA_INVALID",
    "message": "meeting_type 在 project_type=MICRO 时必填",
    "retryable": false
  }
}
```

---

## 4. 查询结果

`GET /v1/retail_meeting_checks/{task_id}`

**返回类型：** 进行中 → §4.1；终态 → §5。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `task_id` | path | `string` | 提交时的 ID |

```bash
curl -X GET 'https://retail-meeting-check-test.example.com/v1/retail_meeting_checks/req-micro-000090-001' \
  -H 'Authorization: Bearer YOUR_API_TOKEN'
```

### 4.1 进行中

`overall_status` 为 `null` → 继续轮询：

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | `string` | 请求 ID |
| `meeting_id` | `string` | 会议 ID（≤36） |
| `overall_status` | `null` | 进行中固定为 `null` |

```json
{
  "task_id": "req-micro-000090-001",
  "meeting_id": "1090",
  "overall_status": null
}
```

终态：`overall_status` ∈ `PASS` \| `FAIL` \| `NEED_HUMAN` \| `ERROR`。

---

## 5. 终态响应（结构化）

### 5.1 PE 后处理要回答的问题

1. **整场结论？** → `overall_status`（必要时看 `error`）  
2. **哪张材料不合格 / 灰区？** → `photo_results[].photo_status`  
3. **为什么？** → `photo_results[].fail_reasons[].reason_code`（文案 PE 自映射）

### 5.2 顶层字段（simple 最瘦）

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | `string` | 请求 ID |
| `meeting_id` | `string` | 会议 ID（≤36） |
| `overall_status` | `string` enum | `PASS` \| `FAIL` \| `NEED_HUMAN` \| `ERROR` |
| `error` | `object` | **仅** `overall_status=ERROR` 时出现 |
| `photo_results` | `AssetResult[]` | **按图主结构**（§5.3） |

**`error`（仅 overall=`ERROR`）**

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | `string` | 错误码 |
| `message` | `string` | 可读说明 |
| `retryable` | `boolean` | 是否可重试 |

### 5.3 `photo_results[]`（按图主结构）

每张提交材料一条，用 `photo_id` 对齐缩略图（类型以 PE 本地提交记录为准）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `photo_id` | `string` | 材料 ID（与提交一致，≤36） |
| `photo_status` | `string` enum | `PASS` \| `FAIL` \| `UNCERTAIN` \| `ERROR` |
| `fail_reasons` | `object[]` | 该图原因；通过时为 `[]`；每项仅含 `reason_code` |

**`fail_reasons[]`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `reason_code` | `string` \| `null` | **机器码（分支 / i18n 主键）**；文案由 PE 自映射 |

**PE 后处理建议：**

- 写回会议：看 `overall_status`
- 页面主数据：遍历 `photo_results`，`FAIL`/`UNCERTAIN`/`ERROR` 标红黄（如「2/4 张需处理」由 PE 自算）
- 原因：用 `reason_code` 映射文案；**同一图多个码时建议全部展示**（或主文案 +「等 N 项」）

### 5.4 会议状态映射（务必区分）

| `overall_status` | PE 建议处理 |
|------------------|-------------|
| `PASS` | 标记通过 |
| `FAIL` | 标记不通过；用户可改材料后 **换新 `task_id`** 重提 |
| `NEED_HUMAN` | **待人工**，不要当成 FAIL |
| `ERROR` | **系统错误**：保持待校验并告警重试；**不要**记业务不合格 |

### 5.5 产品语义（避免联调扯皮）

| 点 | 约定 |
|----|------|
| `photo_status=UNCERTAIN` | 该图灰区；页面建议标黄。整场是否 `NEED_HUMAN` 由 AI 聚合，**不要** PE 自己把「有 UNCERTAIN」强行改成 FAIL |
| `NEED_HUMAN` | PE 进入人工队列；**人工结论不回传 AI**。超时/升级策略由 PE 产品定 |
| `FAIL` vs `ERROR` | FAIL=业务不合格可改材料重提；ERROR=系统问题，修权限/URI/服务后再提，**不记业务不合格** |
| 多 `reason_code` | 数组可 >1；映射表见 §9；未知码用兜底文案，并反馈 AI 补码 |
| 类型展示 | simple **不下发** `photo_type`；用 PE 本地 `photo_id → 类型/缩略图` 对齐 |

---

## 6. 响应示例

### 6.1 FAIL

```json
{
  "task_id": "req-hall-x-002",
  "meeting_id": "1009",
  "overall_status": "FAIL",
  "photo_results": [
    { "photo_id": "201", "photo_status": "PASS", "fail_reasons": [] },
    {
      "photo_id": "203",
      "photo_status": "FAIL",
      "fail_reasons": [{ "reason_code": "NAME_SET_MISMATCH" }]
    },
    {
      "photo_id": "210",
      "photo_status": "FAIL",
      "fail_reasons": [{ "reason_code": "COUNT_BELOW_THRESHOLD" }]
    }
  ]
}
```

### 6.2 PASS（节选）

```json
{
  "task_id": "req-hall-2-20260417-001",
  "meeting_id": "1002",
  "overall_status": "PASS",
  "photo_results": [
    { "photo_id": "201", "photo_status": "PASS", "fail_reasons": [] },
    { "photo_id": "203", "photo_status": "PASS", "fail_reasons": [] }
  ]
}
```

### 6.3 NEED_HUMAN

```json
{
  "task_id": "req-micro-y-003",
  "meeting_id": "1100",
  "overall_status": "NEED_HUMAN",
  "photo_results": [
    {
      "photo_id": "401",
      "photo_status": "UNCERTAIN",
      "fail_reasons": [{ "reason_code": "BLURRY" }]
    }
  ]
}
```

### 6.4 ERROR

```json
{
  "task_id": "req-micro-z-004",
  "meeting_id": "1101",
  "overall_status": "ERROR",
  "error": {
    "code": "S3_NOT_FOUND",
    "message": "对象不存在: s3://pe-meetings/micro/1101/poster.jpg",
    "retryable": false
  },
  "photo_results": [
    {
      "photo_id": "501",
      "photo_status": "ERROR",
      "fail_reasons": [{ "reason_code": "S3_NOT_FOUND" }]
    }
  ]
}
```

看 `error.retryable`：可重试则告警后重提；不可重试则先修数据。**不要**写成业务不合格。

---

## 7. 回调（可选）

提交时带 `X-Callback-URL`，审核结束后 AI 向该地址 `POST` **终态结果**（结构与 §5 / §6 相同）。

| Header | 说明 |
|--------|------|
| `Content-Type` | `application/json` |
| `X-Request-Id` | 对应 `task_id` |
| `X-Signature` | `sha256=` + HMAC-SHA256(**原始 Body 字节**，双方约定密钥) 的**小写 hex**；前缀 `sha256=` |

**密钥：** 联调前线下交换；测试/生产可不同。未配置密钥时，以实现为准（可能不带 `X-Signature`）——上线前双方确认。

PE 侧要求：

- 5s 内返回 HTTP `2xx`
- 同一 `task_id` **幂等**（可能重复推送；以终态覆盖或忽略重复）
- 非 2xx 时 AI 最多重试 3 次（指数退避）
- 建议：**回调 + 轮询兜底**（回调丢失时靠 GET）
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
| 404 | `task_id` 不存在 |
| 429 | 限流 |
| 500 / 503 | 内部错误 / 依赖不可用 |

### `error.code` / HTTP 错误体（与当前实现一致）

出现位置：HTTP `4xx/5xx` 的 `error` 对象，或终态 `overall_status=ERROR` 时的 `error`。

| code | HTTP（常见） | 可重试 | 说明 |
|------|--------------|--------|------|
| `UNAUTHORIZED` | 401 | N | 缺少 Bearer Token |
| `FORBIDDEN` | 403 | N | Token 无效 / 无权限 |
| `SCHEMA_INVALID` | 400 | N | 请求体校验失败 |
| `IDEMPOTENCY_MISMATCH` | 400 | N | `Idempotency-Key` ≠ `task_id` |
| `NOT_FOUND` | 404 | N | `task_id` 不存在 |
| `RATE_LIMITED` | 429 | Y | 限流 |
| `S3_NOT_FOUND` | 200 终态 ERROR / 业务 FAIL | N | 对象不存在或无法下载 |
| `S3_CORRUPT` | 200 终态 ERROR / 业务 FAIL | N | 文件损坏或无法解析 |
| `ASSET_MISSING` | 200 终态（常业务 FAIL） | N | 缺必审材料或材料不可读 |
| `MODEL_TIMEOUT` | 200 终态 ERROR | Y | 视觉/推理超时 |
| `MODEL_UNAVAILABLE` | 200 终态 ERROR | Y | 模型不可用 |
| `INTERNAL_ERROR` | 500 / 终态 ERROR | Y | 未知内部错误 |

说明：`S3_*` / `ASSET_MISSING` 也可能同时出现在对应图的 `fail_reasons[].reason_code`。

### `reason_code`（全集，与当前规则实现一致）

PE 用下表做 i18n / 埋点主键；simple **只下发码、不下发文案**。未知码走本地兜底文案。

**材料可读 / 下载（也可能出现在 `error.code`）**

| reason_code | 建议文案方向 |
|-------------|--------------|
| `ASSET_MISSING` | 缺少必审材料，或材料不可读 |
| `S3_NOT_FOUND` | 对象不存在 / 无法下载 |
| `S3_CORRUPT` | 文件损坏或无法解析 |

**清晰度 / OCR**

| reason_code | 建议文案方向 |
|-------------|--------------|
| `BLURRY` | 图片不清晰，请重新上传 |
| `OCR_LOW_CONFIDENCE` | 文字识别不清，请换更清晰材料 |

**类型 / 模版 / Logo**

| reason_code | 建议文案方向 |
|-------------|--------------|
| `TYPE_MISMATCH` | 材料类型不符（含微型权益页介绍/日程组合错误） |
| `TYPE_UNCERTAIN` | 材料类型无法可靠判定 |
| `TEMPLATE_MISMATCH` | 版式 / 模版与规定不符 |
| `TEMPLATE_UNCERTAIN` | 模版特征识别不清 |
| `LOGO_MISSING` | 未检出拜耳 Logo |
| `LOGO_UNCERTAIN` | Logo 检出处于灰区 |

**表单一致性 / 主题**

| reason_code | 建议文案方向 |
|-------------|--------------|
| `FIELD_MISMATCH` | 关键字段或水印与表单不一致 |
| `TOPIC_MISMATCH` | 讲者照标题与表单主题不一致 |
| `TOPIC_REUSED` | 讲者照主题与历史会议重复 |
| `NAME_SET_MISMATCH` | 台卡姓名与讲者不符 |

**人数 / 时长**

| reason_code | 建议文案方向 |
|-------------|--------------|
| `COUNT_BELOW_THRESHOLD` | 人数（或签到听众/门店）未达要求 |
| `COUNT_UNCERTAIN` | 人数识别不可靠 |
| `DURATION_BELOW_THRESHOLD` | 签到时长未达要求 |

**手册 / 盗图**

| reason_code | 建议文案方向 |
|-------------|--------------|
| `Manual_NOT_FOUND` | 未识别为宣传手册 |
| `Manual_STALE` | 手册疑似旧版 |
| `IMAGE_DUP` | 与其他会议现场照重复或近似 |

共 **21** 个。后续规则新增码时，AI 侧同步更新本表，PE 补映射行。

---

## 10. 对接检查清单

- [ ] §2.1 真值已齐：Base URL、Token、S3 桶/权限、回调密钥（若启用）  
- [ ] `task_id` 生成规则已实现；重提必换新 ID  
- [ ] S3 已上传且 AI 可读；`file_url` 为 `s3://...`  
- [ ] `POST` + `GET` 轮询（和/或回调）已联调；超时停轮询策略已定  
- [ ] 四种 `overall_status` 已映射；`NEED_HUMAN` ≠ `FAIL`；`ERROR` ≠ 业务不合格  
- [ ] §9 `reason_code` 映射表已落地（含未知码兜底）  
- [ ] 页面以 `photo_results` 按图展开（`photo_id` 对齐本地缩略图）  
- [ ] 回调签名校验 + 幂等 + 轮询兜底（若启用）  
- [ ] 联调联系人 / 加码通知渠道已确认（§12）  

---

## 11. 相关文档

| 文档 | 何时查阅 |
|------|----------|
| **本文** | PE simple 契约权威 |
| [PE接口文档-v1.8.md](PE接口文档-v1.8.md) | 历史全文 / full 排障（**已非 PE 权威**；冲突以本文为准） |
| [PPT字段名对照-第5-6页.md](PPT字段名对照-第5-6页.md) | PPT 中文列 ↔ API 字段名 |
| [schemas/retail-meeting-check-request.schema.json](schemas/retail-meeting-check-request.schema.json) | 请求 JSON Schema |
| [schemas/retail-meeting-check-response.schema.json](schemas/retail-meeting-check-response.schema.json) | **full** 响应 Schema（勿用来校验本文 simple） |
| [openapi/pe-retail-meeting-check.v1.yaml](./openapi/pe-retail-meeting-check.v1.yaml) | 机器可读草稿（可能滞后） |

---

## 12. 联系与变更

| 项 | 说明 |
|----|------|
| 联调 / 值班 | （填写：负责人、群、邮箱） |
| 缺陷反馈 | 请带 `task_id`、`meeting_id`、时间、HTTP 状态、响应摘要 |
| `reason_code` / 契约变更 | AI 侧更新本文 §9 与投影行为后 **主动通知 PE**；PE 补映射行后再发版 |
| 文档冲突 | **以本文 simple 约定为准** |
