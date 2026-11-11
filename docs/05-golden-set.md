# 黄金集与负样本清单

黄金集用于回归：给定构造的 `RetailMeetingCheckRequest`（PE 信封 `{project,meeting,speakers,meetingPhotos}`，与路径对齐），期望 `overall_status=PASS` 且关键规则 `PASS`。本地目录同时含合格与不合格样本（见下方「本地样本库」）。

路径均相对仓库根：`/Users/ruining.yu/project/零售/`。

**B 项进展（2026-11-02）：** 命名修复、5 场大讲堂黄金夹具、微型 5 场不合格夹具、双讲对照等已落地。机器可读期望见 [`docs/fixtures/expects.json`](fixtures/expects.json)；整理说明见 [`docs/fixtures/README-B样例整理.md`](fixtures/README-B样例整理.md)。

### 本地样本库（照片目录）

#### 药师大讲堂

| 目录 | 场次 | 说明 |
|------|------|------|
| `零售照片ai审核/药师大讲堂/大讲堂已上传过的50场会议核销资料/` | 50 | **整改后的合格版**（含下述 20 场换图后的版本 + 另外 30 场） |
| `零售照片ai审核/药师大讲堂/20场有不合格照片场次&对应执行报告/` | 20 | **换图前的不合格版**；场次 ID 与上表 50 场中的 20 个**重复** |

**重要：** 这 20 场不合格与 50 场里同 ID 的会议**不是同一套图**。不合格包是问题材料尚在时的版本；50 场包里同 ID 目录是业务换图（或补图）之后的合格版。两侧多数其它材料 MD5 相同，但错误明细点名的那张（展架/讲者/海报/全景等）内容不同；场次 340 为保留原全景并新增第二张全景。  
并排对比页：[`零售照片ai审核/药师大讲堂/换图对比-不合格20vs合格50.html`](../零售照片ai审核/药师大讲堂/换图对比-不合格20vs合格50.html)。  
执行报告：仅不合格 20 场有 `不合格照片场次会议执行报告.xlsx`；另 30 场合格无对应执行表。

去重口径：大讲堂唯一会议 **50** = 合格 **30** + 不合格 **20**（不合格 20 ⊆ 原 50 场 ID，但是换图前副本）。

#### 微型药师

| 目录 | 场次 | 说明 |
|------|------|------|
| `零售照片ai审核/微型药师/合格场次45场次/` | 45 | 合格；与不合格无 ID 交集 |
| `零售照片ai审核/微型药师/微型药师20场不合格照片/` | 20 | **新提供**的不合格包 |
| `会议执行报告-11.01.xlsx` | ~70 | 覆盖合格 45 + 不合格 20 + 另 5 场仅有表无图 |

### 当前可跑黄金 / 负样本夹具

| 场次 | 夹具 | overall 期望 |
|------|------|--------------|
| 大讲堂 143 / 204 / 208 / 209 / 224 | `hall-*-pass.json` / `hall-meirui-pass.json` | PASS |
| 大讲堂 185（缺材） | `hall-185-incomplete-fail.json` | FAIL |
| 大讲堂负样本图包 | `hall-negative-samples-fail.json` | FAIL |
| 微型 000606 / 000670 | `micro-000090-pass.json` / `micro-000670-pass.json` | PASS |
| 微型双讲 000921 / 000938 | `micro-000125-pass.json` / `micro-000938-dual-pass.json` | PASS |
| 微型不合格 000728 / 001348 / 001358 / 001453 / 000664 | `micro-*-fail.json` | FAIL |

---

## A. 药师大讲堂黄金场次

### A1. session_no=`2` — 河南美锐大药房

**目录：** `零售照片ai审核/药师大讲堂/大讲堂已上传过的50场会议核销资料/143~2026-6-23~广州东兴堂大药房连锁有限公司核销资料/`（夹具文件名仍为 `hall-meirui-pass.json`）

**表单期望（与结算表/海报一致）：**

| 字段 | 值 |
|------|-----|
| project_type | LECTURE_HALL |
| meeting_date | 2026-04-17 |
| start_time / end_time | 14:00 / 16:10 |
| chain_or_store_name | 河南美锐大药房连锁有限公司 |
| meeting_location | 信阳市六合春宴酒店（信阳师范大学店）（以海报为准） |
| total_attendees | 35 |
| speakers | 高芳、袁芳、刘亭、余艳红（注意：文件夹有「徐艳红」笔误，黄金集姓名以台卡/结算「余艳红」为准） |

**照片映射：**

| photo_type | 文件 | speaker |
|------------|------|---------|
| Poster | `1权益-海报.jpg` | |
| Stand | `2权益-展架.jpg` | |
| TableCard | `3台卡.jpg` | |
| Manual | **缺失** — 见缺口 | |
| SpeakerTitle | `4讲者-高芳1.jpg` | 高芳 |
| SpeakerLecture | `4讲者-高芳2.jpg` | 高芳 |
| SpeakerTitle | `5讲者-袁芳1.jpg` | 袁芳 |
| SpeakerLecture | `5讲者-袁芳2.jpg` | 袁芳 |
| SpeakerTitle | `6讲者-刘亭1.jpg` | 刘亭 |
| SpeakerLecture | `6讲者-刘亭2.jpg` | 刘亭 |
| SpeakerTitle | `7讲者4-徐艳红1.jpg` | 余艳红 |
| SpeakerLecture | `7讲者4-徐艳红2.jpg` | 余艳红 |
| Panorama | `8全景照片-35.jpg` | |
| SignSheet | `9签到表-35（1）.jpg`, `9签到表-35（2）.jpg` | |
| EDM | 本包未单独提供 | 若产品必传需补图或用海报电子版 |

**期望 overall：** `PASS`（拍板：大讲堂 `EDM` / `Manual` 等为**必审**；请求缺类型 → `ASSET_MISSING` FAIL。夹具见 `docs/fixtures/hall-meirui-pass.json`）

**期望规则：**

| rule_code | 期望 status | 备注 |
|-----------|-------------|------|
| KEY_FIELD_MATCH | PASS | 海报日期地点讲者与表单一致 |
| BAYER_LOGO | PASS | 海报/展架/电子日程含赞助方「拜耳医药保健有限公司」 |
| NAME_CARD_SPEAKER_MATCH | PASS | 余艳红/刘亭/袁芳/高芳 |
| PANORAMA_COUNT | PASS | ≥35 |
| SIGNIN_DURATION | PASS | >120（结算 130 分钟） |
| SPEAKER_SHOT_PAIR | PASS | 4 人各 2 张 |
| SPEAKER_TOPIC_OCR | PASS | 标题页主题与表单一致（需正确填 topic） |
| HANDBOOK_DETECT | PASS 或 SKIP | **无独立手册图时 SKIP/缺口** |
| HANDBOOK_NOT_STALE | PASS 或 SKIP | 同上 |

**summary_matched 应包含：** 日期地点一致、台卡四名匹配、Logo、全景人数、签到时长等。

---

## B. 微型药师黄金场次

### B1. session_no=`000090` — 老百姓（安徽）单讲者

**目录：** `微型药师/000090-2026-05-27-合肥市-老百姓大药房连锁（安徽）有限公司/`

| 字段 | 值 |
|------|-----|
| project_type | MICRO |
| meeting_subtype | SINGLE |
| meeting_date | 2026-05-27 |
| chain_or_store_name | 老百姓大药房连锁（安徽）有限公司 |
| meeting_location | 水印/门店：淠河路店（表单应对齐） |

| photo_type | 文件 |
|------------|------|
| EDM | `会议日程.png` |
| EDMDisplay / ProjectIntro | `权益照片1.jpg`, `权益照片2.jpg`（按页类标注） |
| SpeakerTitle | `讲者标题页.jpg` |
| Panorama | `参会人员.jpg` |
| SignSheet | `会议签到表.pdf` |

**期望规则：** `PPT_TEMPLATE_MATCH` PASS、`PPT_PAGE_KIND` PASS、`BAYER_LOGO` PASS、`PANORAMA_COUNT` PASS（≥6）、`SIGNIN_DURATION` PASS（>30）、`SIGNIN_RATIO_AND_STORES` PASS。（水印 / 主题跨会复用规则已下线）

### B2. session_no=`000089` — 淮安广济 单讲者

**目录：** `微型药师/000089-2026-05-29-淮安广济医药连锁有限公司/`

执行报告：汪淳琼，2026-05-29，总参会 7。资产命名同 B1 结构（`会议日程.png`、`权益照片-*`、`讲者照片标题页.jpg`、`参会人员.jpg`、`会议签到表.pdf`）。

**期望：** `overall_status=PASS`（表单人数/讲者与报告对齐后）。

### B3. session_no=`000125` — 山西国大万民 双讲者

**目录：** `微型药师/000125-2026-06-10-山西国大万民药房连锁有限公司/`

| 字段 | 值 |
|------|-----|
| meeting_subtype | DUAL |
| meeting_date | 2026-06-10 |
| speakers | 张辉、张彦文 |
| total_attendees | 14 |

| photo_type | 文件 |
|------------|------|
| EDM | `会议日程.jpg` |
| EDMDisplay / ProjectIntro | `权益照片-1.jpg`, `权益照片-2.jpg` |
| SpeakerTitle | `讲者标题页-1.jpg`, `讲者标题页-2.jpg` |
| Panorama | `参会人员-1.jpg`, `参会人员-2.jpg`（人数合计 ≥12） |
| SignSheet | `会议签到表.pdf` |

**期望：** `PANORAMA_COUNT` PASS（双讲者 ≥12）、`SIGNIN_DURATION` PASS（>60）、其余微型规则 PASS。

---

## C. 样例缺口（影响黄金集满分）

| 缺口 | 影响规则 | 处理 |
|------|----------|------|
| 大讲堂无独立「手册」照片 | HANDBOOK_* | **已实现：无 Manual 资产 → SKIP**；补封面后可跑真规则 |
| 大讲堂无独立「电子日程海报」 | EDM | 补图或产品确认是否可用日程海报电子档 |
| 仅合格样本 | 阈值/召回 | 必须补负样本（见下） |
| 姓名文件名「徐艳红」vs 台卡「余艳红」 | 姓名匹配评测 | 黄金集以 OCR/台卡为准；表单勿用错字 |

---

## D. 需补充的负样本清单

上线前至少各准备若干张（建议每类 ≥3），并标注期望 `FAIL` 或 `NEED_HUMAN`：

| ID | 类型 | 构造方式 | 期望 overall | 期望触发 rule |
|----|------|----------|--------------|---------------|
| N02 | 错模版 | 旧 VI / 非规定权益页（微型） | FAIL | `PPT_TEMPLATE_MATCH`（微型权益） |
| N03 | 无 Logo / 无赞助方 | 微型遮挡 Logo；大讲堂遮挡/抹掉「拜耳医药保健有限公司」 | FAIL | BAYER_LOGO |
| N04 | 旧手册封面 | 往期手册标题/版式 | FAIL | HANDBOOK_NOT_STALE |
| N05 | 非手册 | 普通笔记本特写当 Manual | FAIL | HANDBOOK_DETECT |
| N06 | 台卡缺人 | 仅 3 个台卡入镜 | FAIL | NAME_CARD_SPEAKER_MATCH |
| N07 | 台卡错名 | 姓名与表单不符 | FAIL | NAME_CARD_SPEAKER_MATCH |
| N08 | 人数不足 | 全景明显 <35 / 微型 <6 | FAIL | PANORAMA_COUNT |
| N09 | ~~主题重复~~ | 主题跨会复用已下线 | — | — |
| N09b | 跨会议图片完全重复 | 本场上传与**另一会议**完全相同的文件 | FAIL | IMAGE_DUP |
| N09c | 跨会议图片近似重复 | 本场上传与**另一会议**近似相似的图（压缩/裁剪） | FAIL | IMAGE_DUP |
| N10 | 投影严重倾斜 | 微型权益照极端角度 | NEED_HUMAN 或 FAIL | PPT_TEMPLATE_MATCH |
| N11 | 签到时长不足 | 伪造短时长表头 | FAIL | SIGNIN_DURATION |
| N12 | 签到门店单一 | 微型听众均同一门店 | FAIL | SIGNIN_RATIO_AND_STORES |
| N13 | ~~水印日期错误~~ | 水印规则已下线 | — | — |
| N15 | S3 404 | 错误 file_url | ERROR | S3_NOT_FOUND |
| N16 | 讲者缺过程照 | 大讲堂仅 SpeakerTitle | FAIL | SPEAKER_SHOT_PAIR |
| N17 | 主题不一致 | 标题合影课件≠表单 topic | FAIL | SPEAKER_TOPIC_OCR |
| N18 | 两张同为项目介绍 | 微型缺日程页 | FAIL | PPT_PAGE_KIND |

---

## E. 回归执行建议

1. 将本地文件上传到测试桶，生成真实 `file_url` 的 Request JSON（可放 `docs/fixtures/` 后续补充）
2. 跑 AI 流水线，断言：
   - `overall_status`
   - 关键 `rule_code` 的 `status`
   - `summary_matched` / `summary_failed` 非空策略
3. 负样本集与黄金集分开报告：**黄金集 False FAIL 率**、**负样本漏检率**
4. 阈值变更必须重跑本清单并更新本文档日期

**文档维护：** 新增期数模版或规则时，同步更新本黄金集期望表与 [03-rule-matrix.md](03-rule-matrix.md)。
