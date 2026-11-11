

# 零售会议材料检查 · PE 对接说明

## 1. 接口清单


| 序号  | 方向      | 方法     | 路径                                    | 成功码        | 说明                               |
| --- | ------- | ------ | ------------------------------------- | ---------- | -------------------------------- |
| 1   | PE → AI | `POST` | `/v1/retail_meeting_checks`           | `202`      | 必选                               |
| 2   | PE → AI | `GET`  | `/v1/retail_meeting_checks/{task_id}` | `200`      | 必选（轮询）                           |
| 3   | AI → PE | `POST` | `{X-Callback-URL}`                    | PE 回 `2xx` | **可选**；不带 `X-Callback-URL` 则仅靠轮询 |
| 4   | PE → AI | `GET`  | `/health`                             | `200`      | 可选（探活）                           |


鉴权：`Authorization: Bearer <token>`。未带 → `401`；无效 → `403`。

---

## 2. 提交检查

`POST /v1/retail_meeting_checks`

### 2.1 请求头


| Header         | 必填  | 说明                      |
| -------------- | --- | ----------------------- |
| Authorization  | 是   | `Bearer <token>`        |
| Content-Type   | 是   | `application/json`      |
| X-Callback-URL | 否   | 完成后回调的 HTTPS 地址；不传则只靠轮询 |




### 2.2 请求体

`project`


| 字段                      | 类型       | 说明             |
| ----------------------- | -------- | -------------- |
| `projectId`             | `string` | 项目期数 ID ≤36    |
| `projectType`           | `number` | `1` 大讲堂；`2` 微型 |
| `projectName`           | `string` | 否              |
| `startDate` / `endDate` | `string` | 否              |


`meeting`


| 字段                                                  | 类型        | 说明                                         |
| --------------------------------------------------- | --------- | ------------------------------------------ |
| `meetingId`                                         | `string`  | 会议主键 ≤36                                   |
| `meetingNo`                                         | `string`  | 场次编号 ≤20                                   |
| `meetingName`                                       | `string`  | ≤50                                        |
| `meetingType`                                       | `number`  | `0` 大讲堂；`1` 单讲；`2` 双讲（须与 `projectType` 一致） |
| `meetingDate`                                       | `string`  | `YYYY-MM-DD`                               |
| `startTime` / `endTime`                             | `string`  | `HH:MM`                                    |
| `chainName`                                         | `string`  | 大讲堂必填                                      |
| `pharmacyName`                                      | `string`  | 微型必填                                       |
| `meetingLocation`                                   | `string`  | 地点                                         |
| `remark`                                            | `string`  | 否                                          |
| `totalAttendees`                                    | `integer` | 参会总人数                                      |
| `durationMinutes` / `otherCost` / `meetingTypeName` | —         | 否；有则忽略业务校验                                 |


`speakers[]`


| 字段                   | 类型         | 说明                                           |
| -------------------- | ---------- | -------------------------------------------- |
| `speakerId`          | `string`   | ≤36                                          |
| `identityName`       | `string`   | 身份/职称 ≤10                                    |
| `storeName`          | `string`   | 门店                                           |
| `speakerName`        | `string`   | 姓名                                           |
| `topic`              | `string`   | 主题                                           |
| `serviceMinutes`     | `integer`  | 服务时长（分钟）                                     |
| `lectureFee` / `tax` | `number`   | 否                                            |
| `photos`             | `object[]` | 该讲者材料；大讲堂须成对 `SpeakerTitle`+`SpeakerLecture` |


`speakers[].photos[]` **/** `meetingPhotos[]`


| 字段              | 类型       | 说明                   |
| --------------- | -------- | -------------------- |
| `photoId`       | `string` | ≤36                  |
| `photoType`     | `string` | 见下表；必填               |
| `photoTypeName` | `string` | 材料中文名；**必填**（写入失败 `comments` 前缀） |
| `fileUrl`       | `string` | `s3://` 或 `https://` |
| `fileName`      | `string` | 建议带；用于推断类型           |


**必审** `photoType`**（缺一类 →** `FAIL` **+** `ASSET_MISSING`**）**


| 项目                  | 类型                                                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------------------------------------ |
| 大讲堂 `projectType=1` | `EDM` · `Poster` · `Stand` · `TableCard` · `Manual` · `SpeakerTitle` · `SpeakerLecture` · `Panorama` · `SignSheet` |
| 微型 `projectType=2`  | `EDM` · `EDMDisplay` · `ProjectIntro` · `SpeakerTitle` · `Panorama` · `SignSheet`                                  |




### 2.3 请求示例（大讲堂）

```bash
curl -X POST 'https://retail-meeting-check-test.example.com/v1/retail_meeting_checks' \
  -H 'Authorization: Bearer YOUR_API_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "project": {
      "projectId": "P2026Q1",
      "projectType": 1,
      "projectName": "2026年Q1药师大讲堂"
    },
    "meeting": {
      "meetingId": "M0001",
      "meetingNo": "SM2026010001",
      "meetingName": "药师会-第一期",
      "meetingType": 0,
      "meetingDate": "2026-01-15",
      "startTime": "14:00",
      "endTime": "16:00",
      "chainName": "国大药房",
      "pharmacyName": null,
      "meetingLocation": "上海市静安区xx路xx号",
      "remark": "本场为第一季度重点场次",
      "totalAttendees": 42
    },
    "speakers": [
      {
        "speakerId": "S0001",
        "identityName": "药师",
        "storeName": "国大药房静安店",
        "speakerName": "张三",
        "topic": "高血压用药指导",
        "serviceMinutes": 40,
        "photos": [
          {"photoId": "PH0001", "photoType": "SpeakerTitle", "photoTypeName": "标题合影", "fileName": "标题合影_张三.jpg", "fileUrl": "s3://pe-meetings/hall/M0001/speaker_title.jpg"},
          {"photoId": "PH0002", "photoType": "SpeakerLecture", "photoTypeName": "讲课照片", "fileName": "讲课照片_张三.jpg", "fileUrl": "s3://pe-meetings/hall/M0001/speaker_lecture.jpg"}
        ]
      }
    ],
    "meetingPhotos": [
      {"photoId": "PH0003", "photoType": "EDM", "photoTypeName": "电子日程海报", "fileName": "电子海报.jpg", "fileUrl": "s3://pe-meetings/hall/M0001/edm.jpg"},
      {"photoId": "PH0004", "photoType": "Poster", "photoTypeName": "日程海报", "fileName": "海报.jpg", "fileUrl": "s3://pe-meetings/hall/M0001/poster.jpg"},
      {"photoId": "PH0005", "photoType": "Stand", "photoTypeName": "日程展架", "fileName": "展架.jpg", "fileUrl": "s3://pe-meetings/hall/M0001/stand.jpg"},
      {"photoId": "PH0006", "photoType": "TableCard", "photoTypeName": "台卡", "fileName": "台卡.jpg", "fileUrl": "s3://pe-meetings/hall/M0001/tablecard.jpg"},
      {"photoId": "PH0007", "photoType": "Manual", "photoTypeName": "手册", "fileName": "手册.jpg", "fileUrl": "s3://pe-meetings/hall/M0001/manual.jpg"},
      {"photoId": "PH0010", "photoType": "Panorama", "photoTypeName": "参会人员全景", "fileName": "参会人员全景.jpg", "fileUrl": "s3://pe-meetings/hall/M0001/panorama.jpg"},
      {"photoId": "PH0011", "photoType": "SignSheet", "photoTypeName": "签到表", "fileName": "签到表.pdf", "fileUrl": "s3://pe-meetings/hall/M0001/signin.pdf"}
    ]
  }'
```

微型：`project.projectType=2`，`meeting.meetingType=1|2`，并填 `pharmacyName`。

### 2.4 受理响应

`202`（AI 生成 `task_id`，PE 须保存后用于轮询 / 对齐回调）：

```json
{ "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789" }
```

`400`：

```json
{
  "error": {
    "code": "SCHEMA_INVALID",
    "message": "projectType=2（微型）时 meetingType 须为 1 或 2",
    "retryable": false
  }
}
```

---



## 3. 查询结果

`GET /v1/retail_meeting_checks/{task_id}`

进行中（继续轮询）：

```json
{
  "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789",
  "meeting_id": "M0001",
  "overall_status": null
}
```

终态：`overall_status` ∈ `PASS`  `FAIL`  `NEED_HUMAN`  `ERROR`，结构见 §4。

---



## 4. 终态响应


| 字段               | 类型            | 说明                                                 |
| ---------------- | ------------- | -------------------------------------------------- |
| `task_id`        | `string`      | AI 生成的任务 ID（与 `202` 一致）                            |
| `meeting_id`     | `string`      | 会议 ID ≤36                                          |
| `overall_status` | `string` enum | `PASS` | `FAIL` | `NEED_HUMAN` | `ERROR`           |
| `error`          | `object`      | **仅** `ERROR` 时出现：`code` / `message` / `retryable` |
| `photo_results`  | `object[]`    | **仅**不合格 / 待人工 / 系统错误图；整场 `PASS` 时为 `[]` |


`photo_results[]`（**不下发** `photo_status=PASS` 的图）


| 字段             | 类型            | 说明                                      |
| -------------- | ------------- | --------------------------------------- |
| `photo_id`     | `string`      | 与提交一致 ≤36                               |
| `photo_status` | `string` enum | `FAIL` | `UNCERTAIN` | `ERROR`（无 `PASS`） |
| `fail_reasons` | `object[]`    | 见下 |


`fail_reasons[]`


| 字段            | 类型       | 说明 |
| ------------- | -------- | --- |
| `reason_code` | `string` | 机器原因码，全集见 §7 |
| `comments`    | `string` | **中文说明**（后处理）：`{photoTypeName}：{原因文案}`。`photo_status=ERROR` 或系统错误码（`S3_*` / `MODEL_*` / `INTERNAL_ERROR`）**不附**此字段，看顶层 `error.message` |


| `overall_status` | PE 建议                                   |
| ---------------- | --------------------------------------- |
| `PASS`           | 标记通过；`photo_results` 为空                 |
| `FAIL`           | 业务不通过；改材料后 **重新 POST**（AI 发新 `task_id`） |
| `NEED_HUMAN`     | **待人工**                                 |
| `ERROR`          | **系统错误**，告警重试；**不记**业务不合格               |


约定：

- simple **不下发** `photo_type`，也 **不下发** 通过图；用 PE 本地 `photo_id` 映射类型/缩略图；未出现在 `photo_results` 的材料视为通过
- 同一图可有多个 `reason_code`；每项（除 ERROR）带 `comments`（格式 `photoTypeName：原因`）；未知码 AI 兜底为「`photoTypeName`：审核未通过（CODE）」
- `UNCERTAIN` 标黄；整场是否 `NEED_HUMAN` 由 AI 聚合，PE 勿自行改成 FAIL

---



## 5. 响应示例

以下与 §2.3 / §2.4 同一场：`meeting_id=M0001`，`task_id` 为受理返回值；`photo_id` 与请求材料一致。

**FAIL**（仅列不合格图；通过图不下发）

```json
{
  "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789",
  "meeting_id": "M0001",
  "overall_status": "FAIL",
  "photo_results": [
    {
      "photo_id": "PH0006",
      "photo_status": "FAIL",
      "fail_reasons": [
        {
          "reason_code": "NAME_SET_MISMATCH",
          "comments": "台卡：姓名集合是否和表单一致"
        }
      ]
    },
    {
      "photo_id": "PH0010",
      "photo_status": "FAIL",
      "fail_reasons": [
        {
          "reason_code": "COUNT_BELOW_THRESHOLD",
          "comments": "参会人员全景：全景人数是否满足要求"
        }
      ]
    }
  ]
}
```

**PASS**（`photo_results` 为空）

```json
{
  "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789",
  "meeting_id": "M0001",
  "overall_status": "PASS",
  "photo_results": []
}
```

**NEED_HUMAN**

```json
{
  "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789",
  "meeting_id": "M0001",
  "overall_status": "NEED_HUMAN",
  "photo_results": [
    {
      "photo_id": "PH0011",
      "photo_status": "UNCERTAIN",
      "fail_reasons": [
        {
          "reason_code": "OCR_LOW_CONFIDENCE",
          "comments": "签到表：文字手写、AI识别日期不一致"
        }
      ]
    }
  ]
}
```

**ERROR**（系统错误：`fail_reasons` **不附** `comments`，看 `error.message`）

```json
{
  "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789",
  "meeting_id": "M0001",
  "overall_status": "ERROR",
  "error": {
    "code": "S3_NOT_FOUND",
    "message": "对象不存在: s3://pe-meetings/hall/M0001/poster.jpg",
    "retryable": false
  },
  "photo_results": [
    {
      "photo_id": "PH0004",
      "photo_status": "ERROR",
      "fail_reasons": [{ "reason_code": "S3_NOT_FOUND" }]
    }
  ]
}
```

---



## 6. 回调（可选）

提交带 `X-Callback-URL` 时，AI `POST` 终态（结构同 §4 / §5）。

---



## 7. 错误码 / `reason_code`



### HTTP


| HTTP      | 含义            |
| --------- | ------------- |
| 200       | 查询 / 健康检查成功   |
| 202       | 提交已受理         |
| 400       | 参数非法          |
| 401 / 403 | 鉴权失败 / 无权限    |
| 404       | `task_id` 不存在 |
| 429       | 限流            |
| 500 / 503 | 内部错误 / 依赖不可用  |




### `error.code`


| code                | HTTP（常见）               | 可重试 | 说明              |
| ------------------- | ---------------------- | --- | --------------- |
| `UNAUTHORIZED`      | 401                    | N   | 缺少 Bearer Token |
| `FORBIDDEN`         | 403                    | N   | Token 无效 / 无权限  |
| `SCHEMA_INVALID`    | 400                    | N   | 请求体校验失败         |
| `NOT_FOUND`         | 404                    | N   | `task_id` 不存在   |
| `RATE_LIMITED`      | 429                    | Y   | 限流              |
| `S3_NOT_FOUND`      | 200 终态 ERROR / 业务 FAIL | N   | 对象不存在或无法下载      |
| `S3_CORRUPT`        | 200 终态 ERROR / 业务 FAIL | N   | 文件损坏或无法解析       |
| `ASSET_MISSING`     | 200 终态（常业务 FAIL）       | N   | 缺必审材料或不可读       |
| `MODEL_TIMEOUT`     | 200 终态 ERROR           | Y   | 视觉/推理超时         |
| `MODEL_UNAVAILABLE` | 200 终态 ERROR           | Y   | 模型不可用           |
| `INTERNAL_ERROR`    | 500 / 终态 ERROR         | Y   | 未知内部错误          |


`S3_*` / `ASSET_MISSING` 也可能出现在对应图的 `fail_reasons[].reason_code`。

### `reason_code`（全集 25）

simple 下发 `reason_code` + `comments`（中文）。  
**例外：** `photo_status=ERROR` 或系统错误码（`S3_NOT_FOUND` / `S3_CORRUPT` / `MODEL_*` / `INTERNAL_ERROR`）**不附** `comments`，用顶层 `error.message`。未知业务码 AI 兜底「审核未通过（CODE）」。

检测点文案对齐《按材料类型-图像检测清单_枚举检测点》检测点定义表（日期/时间/地点/讲者姓名已拆码）。

| reason_code                | `comments`（中文） |
| -------------------------- | ---------------- |
| `ASSET_MISSING`            | 是否缺少必审材料或材料不可读 |
| `S3_NOT_FOUND`             | （ERROR，无 comments；见 `error.message`）对象不存在 / 无法下载 |
| `S3_CORRUPT`               | （ERROR，无 comments；见 `error.message`）文件损坏或无法解析 |
| `OCR_LOW_CONFIDENCE`       | 文字/要素识别是否清晰可靠 |
| `COMPOSITION_MISSING`      | 讲者和主题页PPT是否同时出现（授课照：讲者与过程PPT是否同时出现） |
| `TEMPLATE_MISMATCH`        | PPT模板特征是否与要求一致 |
| `TEMPLATE_UNCERTAIN`       | 模版特征识别是否清晰可靠 |
| `LOGO_MISSING`             | 是否有拜耳 Logo |
| `LOGO_UNCERTAIN`           | 拜耳 Logo 检出是否清晰可靠 |
| `SPONSOR_MISSING`          | 图最下方是否出现赞助方「拜耳医药保健有限公司」 |
| `SPONSOR_UNCERTAIN`        | 赞助方文案检出是否清晰可靠 |
| `DATE_MISMATCH`            | 日期是否和表单一致 |
| `TIME_MISMATCH`            | 时间是否和表单一致 |
| `LOCATION_MISMATCH`        | 地点是否和表单一致 |
| `SPEAKER_NAME_MISMATCH`    | 讲者姓名是否与表单一致 |
| `TOPIC_MISMATCH`           | 标题是否和表单一致 |
| `NAME_SET_MISMATCH`        | 姓名集合是否和表单一致 |
| `COUNT_BELOW_THRESHOLD`    | 全景人数是否满足要求（大讲堂35人，微型药师单讲者6人，双讲者12人） |
| `COUNT_UNCERTAIN`          | 人数识别是否清晰可靠 |
| `DURATION_BELOW_THRESHOLD` | 会议时长是否满足条件（大讲堂120min，微型药师单讲者30min，双讲者60min） |
| `SIGNIN_INCOMPLETE`        | 签到表是否填写完整 |
| `SIGNIN_COUNT_BELOW`       | 签到人数是否满足要求（大讲堂35人，微型药师单讲者6人，双讲者12人） |
| `HANDBOOK_NOT_FOUND`       | 是否存在菁英药师大讲堂宣传手册封面 |
| `HANDBOOK_STALE`           | 手册是否为当期版本 |
| `IMAGE_DUP`                | 本照片是否和其他场次照片重复 |
