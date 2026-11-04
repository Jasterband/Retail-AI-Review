# B · 样例与数据整理说明

## 命名修复（已落盘）

| 场次 | 变更 |
|------|------|
| 169 | `3权益=展架.jpg` → `3权益-展架.jpg` |
| 183 | `4台卡1/2.jpg` → `4台卡-1/2.jpg`（保留两张台卡） |
| 185 | 缺全景无法补；`4台卡.jpg` 与手册 MD5 相同 → 移入 `_issues/` |
| 218 | `2权益-展架` → `3权益-展架`；`6讲者3-林剑毅*` → `7讲者3-*` |
| 225 | `6讲者2-陈玲.jpg` → `6讲者2-陈玲1.jpg` |
| 208 | `5讲者1彭艳梅*` → `5讲者1-彭艳梅*` |
| 231 | `9签到表（55）.pdf` → `10签到表（55）.pdf` |

## 黄金场夹具（form + assets + s3 map）

| session | 文件 | 期望 |
|---------|------|------|
| 143 | `hall-meirui-pass.json` | PASS |
| 204 | `hall-204-pass.json` | PASS |
| 208 | `hall-208-pass.json` | PASS |
| 209 | `hall-209-pass.json` | PASS |
| 224 | `hall-224-pass.json` | PASS |
| 000606 | `micro-000090-pass.json` | PASS 单讲 |
| 000670 | `micro-000670-pass.json` | PASS 单讲对照 |
| 000921 | `micro-000125-pass.json` | PASS 双讲 |
| 000938 | `micro-000938-dual-pass.json` | PASS 双讲对照 |

讲者姓名取自文件名；日期/连锁取自目录名；`topic` 为占位主题（与海报 OCR 完全对齐需 C 项实跑后再校准）。

## 不合格夹具 + 期望 FAIL 点

汇总见 [`expects.json`](expects.json)。

| session | 文件 | 主要期望失败点 |
|---------|------|----------------|
| 000620 | `micro-000620-fail.json` | `PPT_PAGE_KIND` |
| 000823 | `micro-000823-fail.json` | 业务不合格（实跑确认） |
| 001421 | `micro-001421-fail.json` | 缺标题合影 |
| 001499 | `micro-001499-fail.json` | 缺电子日程海报 |
| 001541 | `micro-001541-fail.json` | 缺电子日程海报展示 |
| 185 | `hall-185-incomplete-fail.json` | 缺全景 / 缺台卡 → SKIP/无法 PASS |
| NEG-HALL | `hall-negative-samples-fail.json` | 模糊、人数不够、信息不全等 |

## Demo

`demo/scenarios.json` 已同步上述可审/浏览场次；验收台场次下拉可直接选跑。
