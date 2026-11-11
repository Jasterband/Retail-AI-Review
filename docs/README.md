# 药师会 AI 审核设计文档

基于 `bayer零售pharmacy engagement方案20261019.pptx` 与本地合格样例，定义 PE ↔ AI 的数据模型与接口契约。

> **代码：** 仓库根目录 `app/`（FastAPI）。启动见根目录 [README.md](../README.md)。

| 文档 | 说明 |
|------|------|
| [README-PE-simple对接.md](README-PE-simple对接.md) | **PE 对接权威契约**（同根目录 `AI_接口文档v2.md`）：`/results`、`flagged_photos`、受理拒绝 `ASSET_MISSING` |
| [fixtures/](fixtures/) | 黄金场 Request JSON + `s3_local_map.json`（本地读图） |
| [PE接口文档-v1.8.md](PE接口文档-v1.8.md) | **历史全文 / full 排障参考**（simple 段落可能滞后，勿当 PE 对接主文档） |
| [PPT字段名对照-第5-6页.md](PPT字段名对照-第5-6页.md) | **对接变量名**：PPT 第 5/6 页中文列 ↔ API 字段（改 PPT 先改这里） |
| [CRM与AI-API字段对照.md](CRM与AI-API字段对照.md) | **CRM 库字段 ↔ AI API**：PE 组包/落库映射表 |
| [AI审核开发前置条件.md](AI审核开发前置条件.md) | **开工前**：必须/建议齐备项、对外对齐、技术拍板、启动顺序 |
| [技术选型与数据存储.md](技术选型与数据存储.md) | FastAPI；SQLite→RDS PG；最终结果 simple/full；中间结果 debug 表 |
| [检测点清单与photo_results.md](检测点清单与photo_results.md) | 主题=OCR文字；照片盗用=pHash/embedding（仅跨会）；**full** checks 清单 |
| [按材料类型-图像检测清单.md](按材料类型-图像检测清单.md) | **按材料类型**：图上要检什么（单张 checks + 场级汇总） |
| [thresholds.md](thresholds.md) | 默认阈值摘录（与 `app/services/thresholds.py` / 规则矩阵对齐） |
| [openapi/pe-retail-meeting-check.v1.yaml](openapi/pe-retail-meeting-check.v1.yaml) | OpenAPI 草稿（**可能滞后**；PE simple 以对接文档为准） |
| [01-er-field-dictionary.md](01-er-field-dictionary.md) | ER 图、表字段字典、枚举 |
| [sql/schema.sql](sql/schema.sql) | 参考 DDL |
| [schemas/retail-meeting-check-request.schema.json](schemas/retail-meeting-check-request.schema.json) | 请求 JSON Schema |
| [schemas/retail-meeting-check-pe-response.schema.json](schemas/retail-meeting-check-pe-response.schema.json) | **PE v2** 响应 JSON Schema（`flagged_photos`） |
| [schemas/retail-meeting-check-response.schema.json](schemas/retail-meeting-check-response.schema.json) | **full** 内部落库 JSON Schema（勿校验 PE 响应） |
| [03-rule-matrix.md](03-rule-matrix.md) | 规则矩阵（阈值 / UNCERTAIN / 人工） |
| [04-template-pack.md](04-template-pack.md) | 模版 pack 与 crop 清单 |
| [05-golden-set.md](05-golden-set.md) | 黄金集期望输出与负样本清单 |
| [../demo/](../demo/) | **交互 Demo**：照片 + checks 检测点 + rule_results（mock） |

## 职责边界

- **PE**：期数、会议表单、讲者次数/主题业务校验、状态机、推送 AI、写回结果
- **AI**：读 S3、OCR/检测、与表单比对、模版/Logo/人数、图片完全一致查重、讲者主题查重、结构化输出
- **人工**：`NEED_HUMAN` / 低置信度 / 管理员改状态（乐观锁）

## 默认产品决策

1. 总状态三级：`PASS` / `FAIL` / `NEED_HUMAN`（不并入 FAIL）
2. 地点比对：OCR 地点 vs `form.meeting_location`；连锁/药店名另字段
3. 手册：封面识别 + 旧版模版；**照片盗用**=跨会同组查重（有人/无人分组；海报类仅完全一致；不查会内）
