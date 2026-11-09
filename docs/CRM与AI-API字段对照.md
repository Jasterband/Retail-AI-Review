# CRM 与 AI API 字段对照

> 来源：`CRM数据字典20261105.xlsx` ↔ AI 请求/响应契约。  
> **PE 响应形状**以 [README-PE-simple对接.md](README-PE-simple对接.md) 为准；请求字段与枚举可对照本文 + [schemas/](schemas/)。历史全文见 [PE接口文档-v1.8.md](PE接口文档-v1.8.md)。  
> **约定：** 两边变量名可以不同；PE 组包 / 落库时按本表映射。AI 只认 API 字段名。  
> **Excel：** `CRM数据字典20261105.xlsx`（或根目录「附 ai 端」副本）已加两列：**F「AI API 字段」**、**G「AI 需要类型」**（simple 契约），并附 `PhotoType` 码表；本文与 Excel 同步维护。  
> **类型转换由 PE 在组包时完成**；AI 只收 G 列类型。

---

## 0. 总原则

| 侧 | 命名 | 职责 |
|----|------|------|
| CRM | PascalCase 库字段 | 持久化 |
| AI API | snake_case JSON | 审核入参 / 出参 |

- 语义能对上即可，**不必改成同名**。
- 有「合成 / 拆分 / 枚举转码 / 类型转换」的，以「映射备注」为准。
- AI 独有字段（如 `task_id`、`options`）CRM 无对应列，由 PE 生成或省略。

---

## 1. 项目期数 `r_Seminar_Project`

| CRM 字段 | 类型（库） | AI API | 落在请求 | 映射备注 |
|----------|------------|--------|----------|----------|
| `ProjectID` | nvarchar(36) PK | `project_id` | 顶层 | **同为字符串**（API `string` ≤36） |
| `ProjectType` | int | `project_type` | 顶层 | `1`→`LECTURE_HALL`；`2`→`MICRO` |
| `ProjectName` | nvarchar(100) | （无） | — | 展示用；AI 不收，可用 `project_id` |
| `StartDate` / `EndDate` / `Status` 等 | — | （无） | — | PE 自用 |

---

## 2. 会议执行记录 `r_Seminar` → 顶层 + `form`

| CRM 字段 | 中文 | AI API | 落在请求 | 映射备注 |
|----------|------|--------|----------|----------|
| `MeetingID` | 会议ID | `meeting_id` | 顶层 | **同为字符串**（API `string` ≤36，可直接传 GUID） |
| `MeetingNo` | 场次编号 | `meeting_no` | 顶层 | 直接映射 |
| `ProjectID` | 项目期数ID | `project_id` | 顶层 | **同为字符串** |
| `ProjectType` | 项目类型 | `project_type` | 顶层 | `1`→`LECTURE_HALL`；`2`→`MICRO` |
| `ProjectName` | 项目类型名称 | （无） | — | 不传 AI |
| `MeetingName` | 会议名称 | `meeting_name` | `form` | 直接映射 |
| `MeetingType` | 会议类型 | `meeting_type` | 顶层 | **结构不同**：见下方枚举 |
| `MeetingDate` | 会议日期 | `meeting_date` | `form` | `YYYY-MM-DD` |
| `StartTime` | 开始时间 | `start_time` | `form` | `HH:mm` |
| `EndTime` | 结束时间 | `end_time` | `form` | `HH:mm` |
| `DurationMinutes` | 会议时长 | （无） | — | AI 不收；可由起止推算 |
| `ChainName` | 连锁名称 | `chain_or_store_name` | `form` | **合成**：大讲堂取 `ChainName` |
| `PharmacyName` | 药店名称 | `chain_or_store_name` | `form` | **合成**：微型取 `PharmacyName` |
| `MeetingLocation` | 会议地点 | `meeting_location` | `form` | 直接映射 |
| `Remark` | 备注 | `remark` | `form` | 可空 |
| `TotalAttendees` | 总参会人数 | `total_attendees` | `form` | 直接映射 |
| `OtherCost` | 其他费用 | （无） | — | PPT 曾称 `other_fee`；AI 审核不依赖 |
| `CheckStatus` | 校验状态 | （无） | — | **PE 自维**；勿塞进 AI 请求 |
| `AiCheckResult` | AI 结论摘要 | 响应侧写回 | — | 可由 `overall_status` + 摘要回写 |
| `AiCheckTimes` | AI 校验次数 | ≈ 响应 `attempt_no` | — | PE 每次提交 +1 / 或读 AI 响应 |
| `ZipFile*` / 审计字段等 | — | （无） | — | PE 自用 |

### 2.1 `MeetingType` ↔ `meeting_type` + `project_type`

| CRM `MeetingType` | 含义 | AI |
|-------------------|------|-----|
| `0` | 药师大讲堂 | `project_type=LECTURE_HALL`，`meeting_type=null` |
| `1` | 单讲者 | `project_type=MICRO`，`meeting_type=SINGLE` |
| `2` | 双讲者 | `project_type=MICRO`，`meeting_type=DUAL` |

> 注意：CRM 把「是否大讲堂」和「单/双讲」压在一个 `MeetingType`；AI 拆成 `project_type` + `meeting_type`。

---

## 3. 讲者 `r_Seminar_Speaker` → `form.speakers[]`

| CRM 字段 | 中文 | AI API | 映射备注 |
|----------|------|--------|----------|
| `SpeakerID` | 讲者ID | `speaker_id` | **同为字符串**；须与 `photos[].speaker_id` 同一套编码 |
| `MeetingID` | 会议ID | （隐含） | 挂在请求的 `meeting_id` 下，不单独传 |
| `IdentityName` | 身份 | `identity_name` | **必填**（CRM NotNull，≤10） |
| `StoreName` | 所属门店 | `store_name` | 必填 |
| `SpeakerName` | 姓名 | `speaker_name` | 必填 |
| `Topic` | 讲者主题 | `topic` | 必填；主题查重用 |
| `ServiceMinutes` | 服务时长（分钟） | `service_minutes` | 必填 |
| `LectureFee` | 讲课费 | `lecture_fee` | **必填**（CRM NotNull） |
| `Tax` | 税金 | `tax` | **必填**（CRM NotNull） |
| `Sort` | 排序 | （无） | PE 按此排 `speakers[]` 顺序；不单独传 AI |

---

## 4. 证据链照片 `r_Seminar_Photo` → `photos[]`

| CRM 字段 | 中文 | AI API | 映射备注 |
|----------|------|--------|----------|
| `PhotoID` | 照片ID | `photo_id` | **同为字符串** |
| `MeetingID` | 会议ID | （隐含） | |
| `SpeakerID` | 讲者ID | `speaker_id` | 会议级照片库为 Null → API 省略；讲者照必填 |
| `PhotoType` | 照片类型 | `photo_type` | **同值直传**，见 §4.1；讲者照两类均须带 `speaker_id` |
| `FileUrl` / `FilePath` | 文件地址 | `file_url` | 须转成 `s3://...`（或 PE 已存 S3 URI） |
| `FileExt` / `FileName` | 扩展名等 | → `content_type` | 由扩展名推：`jpg/jpeg/png/pdf` |
| `Sort` | 排序 | `sort` | **必填**（CRM NotNull，≥1） |

### 4.1 `PhotoType` = `photo_type`（同值）

| CRM / AI `photo_type` | 含义 | 适用项目 |
|----------------------|------|----------|
| `EDM` | 电子日程海报 | 大讲堂 / 微型 |
| `Poster` | 日程海报 | 大讲堂 |
| `Stand` | 日程展架 | 大讲堂 |
| `TableCard` | 台卡 | 大讲堂 |
| `Manual` | 手册 | 大讲堂 |
| `EDMDisplay` | 电子日程海报展示 | 微型 |
| `ProjectIntro` | 项目介绍展示 | 微型 |
| `Panorama` | 参会人员全景 | 大讲堂 / 微型 |
| `SignSheet` | 签到表 | 大讲堂 / 微型 |
| `SpeakerTitle` | 标题合影 | 大讲堂 / 微型（须 `speaker_id`） |
| `SpeakerLecture` | 讲课照片 | 大讲堂成对；微型按规则（须 `speaker_id`） |

> 已取消 `speaker_shot_kind`；讲者照直接用 CRM 的两种 `PhotoType`。

---

## 5. AI 校验结果 `r_Seminar_Ai_CheckResult` ↔ 响应写回

| CRM 字段 | AI 侧 | 说明 |
|----------|-------|------|
| `AiCheckID` | （PE 自生成） | |
| `MeetingID` | 请求 `meeting_id` | |
| `TaskID` | ≈ `task_id` | 外部任务号，建议与提交时 `task_id` 对齐 |
| `AiCheckResult` | 终态**摘要** | CRM `nvarchar(500)`；只写短摘要，**勿**塞 `photo_results`/`rule_results` 全文 |
| `CheckStatus` | 任务态 | `APPROVING` / `FINISHED`；与会议表 `CheckStatus`（int）不同层 |

会议表写回建议：

| CRM（`r_Seminar`） | 来源 |
|--------------------|------|
| `CheckStatus`（int） | 见下方映射 |
| `AiCheckResult` | 摘要文案（≤500） |
| `AiCheckTimes` | +1 或同步 `attempt_no` |

| AI `overall_status` | CRM `r_Seminar.CheckStatus` | 说明 |
|---------------------|-----------------------------|------|
| （处理中） | `1` 待校验 | `Ai_CheckResult.CheckStatus=APPROVING` |
| `PASS` | `2` 通过 | |
| `FAIL` | `3` 不通过 | 可改材料后换新 `task_id` |
| `NEED_HUMAN` | `1` 待校验 | 待人工；勿当成 FAIL |
| `ERROR` | `1` 待校验（建议） | 系统错误；告警重试，勿记业务不合格 |

| AI 响应字段 | CRM | 说明 |
|-------------|-----|------|
| `overall_status` | → 会议 `CheckStatus`（上表） | |
| `attempt_no` | → `AiCheckTimes` | |
| `task_id` | → `TaskID` | |
| `rule_results` / `photo_results` | **另存或只给前端**；不进 `AiCheckResult` nvarchar(500) | |

---

## 6. 仅 AI 有、CRM 无（PE 生成即可）

| AI 字段 | 说明 |
|---------|------|
| `task_id` | 每次提交唯一任务号 |
| `content_type` | 材料 MIME |
| `refs` / `options` | 可选；联调常省略 |
| 响应 `rule_results`、`photo_results` 等 | 审核明细 |

---

## 7. PE 组包伪代码（速查）

```text
request.meeting_id     ← MeetingID                 # string，可直传
request.meeting_no     ← MeetingNo
request.project_id      ← ProjectID                 # string，可直传
request.project_type   ← ProjectType 1|2 → LECTURE_HALL|MICRO
request.meeting_type← MeetingType 0→null; 1→SINGLE; 2→DUAL

form.meeting_name           ← MeetingName
form.meeting_date           ← MeetingDate
form.start_time / end_time  ← StartTime / EndTime
form.chain_or_store_name    ← ChainName if 大讲堂 else PharmacyName
form.meeting_location               ← MeetingLocation
form.remark                 ← Remark
form.total_attendees        ← TotalAttendees
form.speakers[]             ← r_Seminar_Speaker 按 Sort
photos[]                    ← r_Seminar_Photo：PhotoType 直传 + FileUrl→file_url
```

---

## 8. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-11-05 | 初版：按 CRM 数据字典 20261105 与 AI API v1.8 整理对照 |
| 2026-11-05 | **ID 类型对齐 CRM nvarchar**：`meeting_id` / `project_id` / `speaker_id` / `photo_id` 由 `integer` 改为 API `string`（≤36）；枚举/数量字段仍按原契约 |
| 2026-11-05 | **长度/格式对齐 CRM**：`task_id`≤50；表单/讲者/地点等 `maxLength`；`meeting_date`/`HH:mm` 格式校验。`ProjectType`/`MeetingType` 仍由 PE 转码为字符串枚举 |
| 2026-11-05 | **API 字段名对齐 CRM（snake_case）**：`MeetingNo`→`meeting_no`，`ProjectID`→`project_id`，`assets`→`photos`，`request_id`→`task_id` 等；`chain_or_store_name` / `content_type` 仍为 AI 约定 |
| 2026-11-05 | **`photo_type` 枚举与 CRM `PhotoType` 同值**；去掉 `speaker_shot_kind`（讲者照用 `SpeakerTitle`/`SpeakerLecture`） |
| 2026-11-05 | **对齐 CRM NotNull**：`identity_name` / `lecture_fee` / `tax` / `photos[].sort` 改为 API 必填；`AiCheckResult` 仅摘要；补会议 `CheckStatus` 回写码表 |
