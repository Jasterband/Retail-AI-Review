# 零售会议材料检查

---

## 1. 接口清单


| 序号  | 方向      | 方法     | 路径                                            | 说明                |
| --- | ------- | ------ | --------------------------------------------- | ----------------- |
| 1   | PE → AI | `POST` | `/v1/retail_meeting_checks`                   | 提交检查，返回 `task_id` |
| 2   | PE → AI | `GET`  | `/v1/retail_meeting_checks/{task_id}/results` | 轮询结果              |
| 3   | AI → PE | `POST` | `{X-Callback-URL}`                            | 可选回调；不带则只靠轮询      |
| 4   | PE → AI | `GET`  | `/health`                                     | 可选探活              |


---



## 2. 提交检查

`POST /v1/retail_meeting_checks`

### 2.1 请求头


| Header         | 必填  | 说明                 |
| -------------- | --- | ------------------ |
| Authorization  | 是   | `Bearer <token>`   |
| Content-Type   | 是   | `application/json` |
| X-Callback-URL | 可选  | 完成后回调的 HTTPS 地址    |




### 2.2 请求体

```json
{
  "project": { ... },
  "meeting": { ... },
  "speakers": [ ... ],
  "meetingPhotos": [ ... ]
}
```


| 字段              | 类型         | 必填  | 说明                |
| --------------- | ---------- | --- | ----------------- |
| `project`       | `object`   | 是   | 项目期信息             |
| `meeting`       | `object`   | 是   | 本场会议信息            |
| `speakers`      | `object[]` | 是   | 讲者列表；每人带 `photos` |
| `meetingPhotos` | `object[]` | 是   | 场级材料              |




#### 2.2.1 `project`


| 字段            | 类型       | 必填  | 说明                  |
| ------------- | -------- | --- | ------------------- |
| `projectId`   | `string` | 是   | 项目期数 ID             |
| `projectType` | `number` | 是   | `1` 大讲堂；`2` 微型      |
| `projectName` | `string` | 是   | 项目名称                |
| `startDate`   | `string` | 可选  | 项目期开始日，`YYYY-MM-DD` |
| `endDate`     | `string` | 可选  | 项目期结束日，`YYYY-MM-DD` |




#### 2.2.2 `meeting`


| 字段                | 类型        | 必填  | 说明                                         |
| ----------------- | --------- | --- | ------------------------------------------ |
| `meetingId`       | `string`  | 是   | 会议主键                                       |
| `meetingNo`       | `string`  | 是   | 场次编号                                       |
| `meetingName`     | `string`  | 是   | 会议名称                                       |
| `meetingType`     | `number`  | 是   | `0` 大讲堂；`1` 单讲；`2` 双讲（须与 `projectType` 一致） |
| `meetingDate`     | `string`  | 是   | `YYYY-MM-DD`                               |
| `startTime`       | `string`  | 是   | `HH:MM`                                    |
| `endTime`         | `string`  | 是   | `HH:MM`                                    |
| `chainName`       | `string`  | 条件  | 大讲堂必填                                      |
| `pharmacyName`    | `string`  | 条件  | 微型必填；大讲堂 PE 固定传 `null`                     |
| `meetingLocation` | `string`  | 是   | 地点                                         |
| `totalAttendees`  | `integer` | 是   | 参会总人数                                      |
| `durationMinutes` | `integer` | 是   | 时长（分钟）                                     |
| `meetingTypeName` | `string`  | 可选  | 会议类型中文名                                    |




#### 2.2.3 `speakers[]`


| 字段               | 类型         | 必填  | 说明                                       |
| ---------------- | ---------- | --- | ---------------------------------------- |
| `speakerId`      | `string`   | 是   | 讲者 ID                                    |
| `identityName`   | `string`   | 可选  | 身份/职称                                    |
| `storeName`      | `string`   | 是   | 门店                                       |
| `speakerName`    | `string`   | 是   | 姓名                                       |
| `topic`          | `string`   | 是   | 讲题                                       |
| `serviceMinutes` | `integer`  | 是   | 服务时长（分钟）                                 |
| `photos`         | `object[]` | 是   | 大讲堂须成对 `SpeakerTitle` + `SpeakerLecture` |




#### 2.2.4 照片对象（`speakers[].photos[]` 与 `meetingPhotos[]` 相同）


| 字段              | 类型       | 必填  | 说明                         |
| --------------- | -------- | --- | -------------------------- |
| `photoId`       | `string` | 是   | 照片 ID                      |
| `photoType`     | `string` | 是   | 材料类型，见下表                   |
| `photoTypeName` | `string` | 是   | 材料中文名（写入失败 `comments` 前缀）  |
| `fileUrl`       | `string` | 是   | `s3://...` 或 `https://...` |




#### 2.2.5 必审 `photoType`

缺一类 → 受理拒绝，码 `ASSET_MISSING`（不创建 `task_id`，见 §2.4）。


| 项目  | `projectType` | 必审类型                                                                                                               |
| --- | ------------- | ------------------------------------------------------------------------------------------------------------------ |
| 大讲堂 | `1`           | `EDM` · `Poster` · `Stand` · `TableCard` · `Manual` · `SpeakerTitle` · `SpeakerLecture` · `Panorama` · `SignSheet` |
| 微型  | `2`           | `EDM` · `EDMDisplay` · `ProjectIntro` · `SpeakerTitle` · `Panorama` · `SignSheet`                                  |


- 讲者材料 → `speakers[].photos`
- 场级材料 → `meetingPhotos`



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
      "totalAttendees": 42,
      "durationMinutes": 120
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
          {"photoId": "PH0001", "photoType": "SpeakerTitle", "photoTypeName": "标题合影", "fileUrl": "s3://pe-meetings/hall/M0001/speaker_title.jpg"},
          {"photoId": "PH0002", "photoType": "SpeakerLecture", "photoTypeName": "讲课照片", "fileUrl": "s3://pe-meetings/hall/M0001/speaker_lecture.jpg"}
        ]
      }
    ],
    "meetingPhotos": [
      {"photoId": "PH0003", "photoType": "EDM", "photoTypeName": "电子日程海报", "fileUrl": "s3://pe-meetings/hall/M0001/edm.jpg"},
      {"photoId": "PH0004", "photoType": "Poster", "photoTypeName": "日程海报", "fileUrl": "s3://pe-meetings/hall/M0001/poster.jpg"},
      {"photoId": "PH0005", "photoType": "Stand", "photoTypeName": "日程展架", "fileUrl": "s3://pe-meetings/hall/M0001/stand.jpg"},
      {"photoId": "PH0006", "photoType": "TableCard", "photoTypeName": "台卡", "fileUrl": "s3://pe-meetings/hall/M0001/tablecard.jpg"},
      {"photoId": "PH0007", "photoType": "Manual", "photoTypeName": "手册", "fileUrl": "s3://pe-meetings/hall/M0001/manual.jpg"},
      {"photoId": "PH0010", "photoType": "Panorama", "photoTypeName": "参会人员全景", "fileUrl": "s3://pe-meetings/hall/M0001/panorama.jpg"},
      {"photoId": "PH0011", "photoType": "SignSheet", "photoTypeName": "签到表", "fileUrl": "s3://pe-meetings/hall/M0001/signin.pdf"}
    ]
  }'
```

微型：`projectType=2`，`meetingType=1|2`，填 `pharmacyName`。

### 2.4 受理响应

成功：

```json
{ "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789" }
```

参数错误（请求体不合法，无审核结论）：

```json
{
  "error": {
    "code": "SCHEMA_INVALID",
    "message": "projectType=2（微型）时 meetingType 须为 1 或 2",
    "retryable": false
  }
}
```

说明：`message` 为具体校验失败原因；上例对应字段定义「`meetingType` 须与 `projectType` 一致」。

鉴权失败（无审核结论）：

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "缺少 Bearer Token",
    "retryable": false
  }
}
```

缺必审材料（无 `task_id`、无审核结论）：

```json
{
  "error": {
    "code": "ASSET_MISSING",
    "message": "缺少必审材料: SignSheet",
    "retryable": false
  }
}
```

---



## 3. 查询结果

`GET /v1/retail_meeting_checks/{task_id}/results`

进行中（继续轮询）：

```json
{
  "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789",
  "meeting_id": "M0001",
  "overall_status": "running"
}
```

终态结构见 §4。

---



## 4. 终态响应

**读结果顺序**

先看 `overall_status`：

- `running` → 继续轮询
- `PASS` → 全部通过
- `FAIL` / `NEED_HUMAN` → 有业务问题 → 看 `flagged_photos` → `comments显示中文原因说明`
- `ERROR` → 系统异常 → 看 `error` → `message`


| 字段               | 类型         | 说明                                                         |
| ---------------- | ---------- | ---------------------------------------------------------- |
| `task_id`        | `string`   | 与提交返回一致                                                    |
| `meeting_id`     | `string`   | 会议 ID                                                      |
| `overall_status` | `string`   | `running` 进行中；终态为 `PASS` / `FAIL` / `NEED_HUMAN` / `ERROR` |
| `error`          | `object`   | 仅 `ERROR` 时有：`code` / `message` / `retryable`              |
| `flagged_photos` | `object[]` | 需关注的图；`PASS` 时为 `[]`；不下发通过图                                |


`flagged_photos[]`：


| 字段             | 类型         | 说明                              |
| -------------- | ---------- | ------------------------------- |
| `photo_id`     | `string`   | 与提交一致                           |
| `photo_status` | `string`   | `FAIL` / `ERROR` / `NEED_HUMAN` |
| `fail_reasons` | `object[]` | 原因列表                            |


`fail_reasons[]`：


| 字段            | 类型       | 说明                          |
| ------------- | -------- | --------------------------- |
| `reason_code` | `string` | 机器码，见《图像检测清单》excel     |
| `comments`    | `string` | 中文说明：`{photoTypeName}：{原因}` |


未出现在 `flagged_photos` 的材料视为通过。

---



## 5. 响应示例

**PASS**

```json
{
  "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789",
  "meeting_id": "M0001",
  "overall_status": "PASS",
  "flagged_photos": []
}
```

**FAIL（业务不通过）**

```json
{
  "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789",
  "meeting_id": "M0001",
  "overall_status": "FAIL",
  "flagged_photos": [
    {
      "photo_id": "PH0006",
      "photo_status": "FAIL",
      "fail_reasons": [
        {
          "reason_code": "NAME_SET_MISMATCH",
          "comments": "台卡：姓名集合是否和表单一致"
        }
      ]
    }
  ]
}
```

**NEED_HUMAN（待定）**


**ERROR（系统错误）**

```json
{
  "task_id": "req-a1b2c3d4e5f64789a0b1c2d3e4f56789",
  "meeting_id": "M0001",
  "overall_status": "ERROR",
  "error": {
    "code": "S3_NOT_FOUND",
    "message": "对象不存在或无法下载: s3://pe-meetings/hall/M0001/poster.jpg",
    "retryable": false
  },
  "flagged_photos": []
}
```

---



## 6. 回调（可选）

提交带 `X-Callback-URL` 时，AI `POST` 终态 body（同 §4 / §5）。

---



## 7. 任务相关错误码

出现在终态响应的 `error` 或 `flagged_photos[].fail_reasons`：


| code                        | 常见 `overall_status` | 可重试 | 说明                      |
| --------------------------- | ------------------- | --- | ----------------------- |
| `S3_NOT_FOUND`              | `ERROR`             | N   | 对象不存在或无法下载；终态 ERROR     |
| `INTERNAL_ERROR`            | `ERROR`             | Y   | 很少见：未知内部错误（偶发上游模型不可用）   |
| （业务码，如 `NAME_SET_MISMATCH`） | `FAIL`              | N   | 见检测点清单；在 `fail_reasons` |


业务原因码完整列表见《图像检测清单》excel。