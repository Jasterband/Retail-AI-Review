# CRM 与 AI API 字段对照

> 来源：`CRM数据字典20261105.xlsx` ↔ AI 请求/响应契约。  
> **PE 请求/响应形状**以 [README-PE-simple对接.md](README-PE-simple对接.md) 为准；请求与药师会交互 JSON **同构**（camelCase + 数字枚举 + 嵌套照片）。  
> Schema：[schemas/retail-meeting-check-request.schema.json](schemas/retail-meeting-check-request.schema.json) · OpenAPI：[openapi/pe-retail-meeting-check.v1.yaml](openapi/pe-retail-meeting-check.v1.yaml)。  
> **约定：** CRM 库字段 PascalCase；AI HTTP 入参用交互 JSON 字段名。AI **不要求** PE 再转成旧 snake_case 扁平体。

---

## 0. 总原则

| 侧 | 命名 | 职责 |
|----|------|------|
| CRM | PascalCase 库字段 | 持久化 |
| AI API（请求） | 药师会交互 JSON：`project` / `meeting` / `speakers` / `meetingPhotos` | 审核入参 |
| AI API（响应） | snake_case（`task_id` / `overall_status` / `flagged_photos`…） | 审核出参 |

- 请求侧语义能对上即可；**枚举可直传数字**（`projectType` 1|2，`meetingType` 0|1|2）。
- `task_id` **不在请求体**，由 AI 在 `202` 生成；PE 用 `Idempotency-Key` 做重试幂等。
- AI 内部管道仍用 snake_case snap；边界转换在 AI 侧完成，PE 无感。

---

## 1. 项目期数 `r_Seminar_Project` → `project`

| CRM 字段 | 类型（库） | AI API | 落在请求 | 映射备注 |
|----------|------------|--------|----------|----------|
| `ProjectID` | nvarchar(36) PK | `projectId` | `project` | 字符串 ≤36 |
| `ProjectType` | int | `projectType` | `project` | **直传** `1` 大讲堂 / `2` 微型 |
| `ProjectName` | nvarchar(100) | `projectName` | `project` | 可选 |
| `StartDate` / `EndDate` | — | `startDate` / `endDate` | `project` | 可选 |

---

## 2. 会议执行记录 `r_Seminar` → `meeting`

| CRM 字段 | 中文 | AI API | 落在请求 | 映射备注 |
|----------|------|--------|----------|----------|
| `MeetingID` | 会议ID | `meetingId` | `meeting` | 字符串 ≤36 |
| `MeetingNo` | 场次编号 | `meetingNo` | `meeting` | ≤20 |
| `MeetingName` | 会议名称 | `meetingName` | `meeting` | ≤50 |
| `MeetingType` | 会议类型 | `meetingType` | `meeting` | **直传** `0`/`1`/`2`；须与 `projectType` 一致 |
| `MeetingDate` | 会议日期 | `meetingDate` | `meeting` | `YYYY-MM-DD` |
| `StartTime` | 开始时间 | `startTime` | `meeting` | `HH:mm` |
| `EndTime` | 结束时间 | `endTime` | `meeting` | `HH:mm` |
| `DurationMinutes` | 会议时长 | `durationMinutes` | `meeting` | 可选；**业务时长以签到 OCR 为准** |
| `ChainName` | 连锁名称 | `chainName` | `meeting` | 大讲堂必填 |
| `PharmacyName` | 药店名称 | `pharmacyName` | `meeting` | 微型必填 |
| `MeetingLocation` | 会议地点 | `meetingLocation` | `meeting` | 与海报/水印比对 |
| `Remark` | 备注 | `remark` | `meeting` | 可空 |
| `TotalAttendees` | 总参会人数 | `totalAttendees` | `meeting` | 整数 |
| `OtherCost` | 其他费用 | `otherCost` | `meeting` | 可选；审核不依赖 |
| `CheckStatus` / `AiCheck*` | — | （无） | — | PE 自维 / 响应写回 |

### 2.1 `MeetingType` / `ProjectType`（直传，无需转码）

| CRM `MeetingType` | 含义 | AI |
|-------------------|------|-----|
| `0` | 药师大讲堂 | `projectType=1`，`meetingType=0` |
| `1` | 单讲者 | `projectType=2`，`meetingType=1` |
| `2` | 双讲者 | `projectType=2`，`meetingType=2` |

---

## 3. 讲者 `r_Seminar_Speaker` → `speakers[]`

| CRM 字段 | 中文 | AI API | 映射备注 |
|----------|------|--------|----------|
| `SpeakerID` | 讲者ID | `speakerId` | 字符串；与 `photos` 同套编码 |
| `IdentityName` | 身份 | `identityName` | ≤10 |
| `StoreName` | 所属门店 | `storeName` | |
| `SpeakerName` | 姓名 | `speakerName` | |
| `Topic` | 讲者主题 | `topic` | 主题查重用 |
| `ServiceMinutes` | 服务时长（分钟） | `serviceMinutes` | |
| `LectureFee` | 讲课费 | `lectureFee` | 可选；有则忽略业务校验 |
| `Tax` | 税金 | `tax` | 可选 |
| `Sort` | 排序 | （无） | PE 按此排 `speakers[]` 顺序 |
| （讲者照） | — | `photos[]` | 挂在该讲者下：`SpeakerTitle` / `SpeakerLecture` |

---

## 4. 证据链照片 `r_Seminar_Photo` → `speakers[].photos[]` / `meetingPhotos[]`

| CRM 字段 | 中文 | AI API | 映射备注 |
|----------|------|--------|----------|
| `PhotoID` | 照片ID | `photoId` | 字符串 |
| `SpeakerID` | 讲者ID | （结构） | 有 SpeakerID → 放入对应 `speakers[].photos`；否则 → `meetingPhotos` |
| `PhotoType` | 照片类型 | `photoType` | **同值直传**，见 §4.1 |
| `FileUrl` / `FilePath` | 文件地址 | `fileUrl` | `s3://` 或 `http(s)://` |
| `FileName` | 文件名 | `fileName` | 建议带；用于推断 MIME |
| `Sort` | 排序 | （无） | AI 按数组顺序；不必传 `sort` / `contentType` |

### 4.1 `PhotoType` = `photoType`（同值）

| CRM / AI `photoType` | 含义 | 适用 |
|----------------------|------|------|
| `EDM` | 电子日程海报 | 大讲堂 / 微型 |
| `Poster` | 日程海报 | 大讲堂 |
| `Stand` | 日程展架 | 大讲堂 |
| `TableCard` | 台卡 | 大讲堂 |
| `Manual` | 手册 | 大讲堂 |
| `EDMDisplay` | 电子日程海报展示 | 微型 |
| `ProjectIntro` | 项目介绍展示 | 微型 |
| `Panorama` | 参会人员全景 | 大讲堂 / 微型 |
| `SignSheet` | 签到表 | 大讲堂 / 微型 |
| `SpeakerTitle` | 标题合影 | 须在 `speakers[].photos` |
| `SpeakerLecture` | 讲课照片 | 大讲堂成对；须在 `speakers[].photos` |

---

## 5. AI 校验结果写回（响应侧，仍为 snake_case）

| CRM 字段 | AI 侧 | 说明 |
|----------|-------|------|
| `TaskID` | `task_id` | AI 生成；PE 保存 |
| `AiCheckResult` | 终态摘要 | ≤500；勿塞全文 `photo_results` |
| `CheckStatus` | ← `overall_status` | 见下表 |
| `AiCheckTimes` | PE 自增 / ≈ `attempt_no`（full） | |

| AI `overall_status` | CRM `r_Seminar.CheckStatus` |
|---------------------|-----------------------------|
| （处理中） | `1` 待校验 |
| `PASS` | `2` 通过 |
| `FAIL` | `3` 不通过 |
| `NEED_HUMAN` / `ERROR` | `1` 待校验 |

---

## 6. 仅 AI 有、CRM 无

| 字段 | 说明 |
|------|------|
| 响应 `task_id` | AI 生成 |
| 可选 `refs` / `options` | 联调常省略 |
| 响应 `flagged_photos` 等 | 审核明细 |

---

## 7. PE 组包伪代码（速查）

```text
project.projectId / projectType / projectName  ← ProjectID / ProjectType / ProjectName
meeting.meetingId / meetingNo / meetingName    ← MeetingID / MeetingNo / MeetingName
meeting.meetingType                            ← MeetingType（0|1|2 直传）
meeting.meetingDate / startTime / endTime      ← MeetingDate / StartTime / EndTime
meeting.chainName / pharmacyName               ← ChainName / PharmacyName
meeting.meetingLocation / remark / totalAttendees ← …

speakers[]                                     ← r_Seminar_Speaker（含 photos[] 讲者照）
meetingPhotos[]                                ← 无 SpeakerID 的 r_Seminar_Photo
# 不要再组 task_id / form / 顶层扁平 photos / LECTURE_HALL|MICRO 字符串
```

---

## 8. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-11-05 | 初版：按 CRM 数据字典 20261105 与 AI API v1.8 整理对照 |
| 2026-11-10 | **请求对齐药师会交互 JSON**：camelCase + 数字枚举 + 嵌套照片；PE 免转码；`task_id` 改由 AI 生成 |
