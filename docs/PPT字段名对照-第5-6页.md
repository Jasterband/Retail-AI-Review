# PPT 字段名对照（第 5 / 6 页）· 对接用变量名

> 来源：`bayer零售pharmacy engagement方案20261019.pptx`  
> **第 5 页**「查询会议执行记录」· **第 6 页**「导入会议执行记录」列名一致。  
> 用途：跟 PE 对接时统一「PPT 中文名 ↔ API / 库字段变量名」。  
> **以后 PPT 改了第 5、6 页，优先更新本文。**

对照接口契约：[PE接口文档-v1.8.md](PE接口文档-v1.8.md)

---

## 1. 会议主表字段（导入 / 列表共用列）

| # | PPT 中文名（第 5、6 页） | 建议变量名（API / 代码） | 落在请求里 | 必填（PPT） | 备注 |
|---|-------------------------|---------------------------|------------|-------------|------|
| 1 | 场次编号 | `session_no` | 顶层 | 是 | ≤20；唯一；大讲堂/微型共用判重 |
| 2 | 项目类型名称 | `period_name`（展示）/ 对接用 `period_id` | 顶层 `period_id` | 是 | PPT 是期数名称；AI 请求传 ID，名称可由 PE 带或不带 |
| 3 | 会议名称 | `meeting_name` | `form.meeting_name` | 是 | ≤50 汉字 |
| 4 | 会议类型 | `meeting_subtype` | 顶层 | 微型必填 | PPT：单讲者 / 双讲者；码：`SINGLE` \| `DUAL`；大讲堂可空 |
| 5 | 会议日期 | `meeting_date` | `form.meeting_date` | 是 | `YYYY-MM-DD` |
| 6 | 会议开始时间 | `start_time` | `form.start_time` | 是 | `HH:mm`（第 5 页展示列写「会议时间」拆成起止） |
| 7 | 会议结束时间 | `end_time` | `form.end_time` | 是 | `HH:mm` |
| 8 | 连锁名称 / 药店名称 | `chain_or_store_name` | `form.chain_or_store_name` | 是 | 大讲堂=连锁；微型=药店 |
| 9 | 会议地点 | `location` | `form.location` | 是 | 与海报/水印比对用这个 |
| 10 | 备注 | `remark` | `form.remark` | 否 | 可空 |
| 11 | 总参会人数 | `total_attendees` | `form.total_attendees` | 是 | 数字 |
| 12 | 其他费用 | `other_fee` | `form.other_fee`（可选扩展） | 否 | 第 6 页：多讲者时「场次编号—其他费用」12 列重复填；AI 审核一般不依赖 |

**第 5 页另有、导入列未必有的展示/状态字段：**

| PPT 中文名 | 建议变量名 | 谁维护 | 备注 |
|------------|------------|--------|------|
| 项目类型（药师大讲堂/微型药师） | `project_type` | PE → AI | 码：`LECTURE_HALL` \| `MICRO`（第 7/9 页新建里也有） |
| 状态 / 校验状态 | `meeting_status` / `check_status` | PE | 待校验 / 通过 / 不通过 / 草稿 |
| AI 校验结果 | `ai_check_result` / 即接口 `overall_status` | AI → PE | `PASS` / `FAIL` / `NEED_HUMAN` / `ERROR` |
| AI 校验次数 | `ai_check_count` / `attempt_no` | PE +1 | 每次提交 AI +1 |

---

## 2. 讲者字段（第 5、6 页「讲者-xxx」）

多讲者：同一 `session_no` 下多行；会议主字段重复填时以第一条为准（PPT 第 6 页说明）。

| # | PPT 中文名 | 建议变量名 | 落在请求里 | 必填 | 备注 |
|---|------------|------------|------------|------|------|
| 1 | 讲者-身份 | `role_title` | `form.speakers[].role_title` | 是（新建页） | ≤10 汉字 |
| 2 | 讲者-所属门店 | `store_name` | `form.speakers[].store_name` | 是 | ≤50 汉字 |
| 3 | 讲者-姓名 | `speaker_name` | `form.speakers[].speaker_name` | 是 | ≤20 汉字；另建议 `speaker_id` |
| 4 | 讲者-讲者主题 | `topic` | `form.speakers[].topic` | 是 | ≤50；主题查重 / 标题合影比对 |
| 5 | 讲者-服务时长（分钟） | `service_minutes` | `form.speakers[].service_minutes` | 是 | 分钟 |
| 6 | 讲者-讲课费 | `fee` | `form.speakers[].fee` | 是（业务） | AI 可不强依赖 |
| 7 | 讲者-税金 | `tax` | `form.speakers[].tax` | 否 | 小数 2 位 |

---

## 3. 枚举取值（对接时对齐）

| 字段 | PPT 说法 | 变量取值 |
|------|----------|----------|
| `project_type` | 药师大讲堂 / 微型药师 | `LECTURE_HALL` / `MICRO` |
| `meeting_subtype` | 单讲者 / 双讲者 | `SINGLE` / `DUAL` |
| 会议状态（PE） | 待校验 / 通过 / 不通过 / 草稿 | 由 PE 自定；AI 侧终态见下 |
| AI 结果 | 通过 / 不通过（+ 待人工扩展） | `PASS` / `FAIL` / `NEED_HUMAN` / `ERROR` |

---

## 4. 和 AI 请求体的对应关系（速查）

```text
PPT 场次编号          → session_no
PPT 项目类型(+名称)   → project_type + period_id
PPT 会议类型          → meeting_subtype
PPT 会议名称/日期/…   → form.*
PPT 讲者-*            → form.speakers[]
（照片不在第 5/6 页列里；见第 7/9/12/13 页 → assets[]）
```

第 5/6 页**没有**照片列；照片材料名在第 7、9、12、13 页，变量用 `assets[].asset_type`（如 `POSTER`、`SPEAKER_PHOTO`）。完整材料枚举见 [PE接口文档-v1.8.md](PE接口文档-v1.8.md) / [AI侧自查-InputOutput与PPT对照.md](AI侧自查-InputOutput与PPT对照.md)。

---

## 5. 是否已在现有 AI 接口字段里？（对照 schema / PE 接口文档）

| 变量名 | 在请求/响应里？ | 说明 |
|--------|-----------------|------|
| `session_no` | ✅ 有 | 顶层必填 |
| `period_id` | ✅ 有 | 顶层必填 |
| `period_name` | ❌ 无 | PPT 展示名；对接用 ID 即可，名称可选以后加 |
| `meeting_name` | ✅ 有 | `form` |
| `meeting_subtype` | ✅ 有 | 顶层；微型必填 |
| `meeting_date` / `start_time` / `end_time` | ✅ 有 | `form` |
| `chain_or_store_name` | ✅ 有 | `form` |
| `location` | ✅ 有 | `form` |
| `remark` | ✅ 有 | `form` 可选 |
| `total_attendees` | ✅ 有 | `form` |
| `other_fee` | ❌ 无 | PPT 有；AI 审核一般不用，未进 schema |
| `project_type` | ✅ 有 | 顶层 |
| `meeting_status` / `check_status` | ❌ 无（也不该有） | **PE 自己维护**，不传给 AI |
| `overall_status`（AI 校验结果） | ✅ 有 | **响应**里 |
| `attempt_no`（AI 校验次数） | ✅ 有 | **响应**里；PE 侧也可自记 `ai_check_count` |
| `role_title` | ✅ 有 | `speakers[]` 可选 |
| `store_name` | ✅ 有 | `speakers[]` 必填 |
| `speaker_name` + `speaker_id` | ✅ 有 | `speakers[]` 必填 |
| `topic` | ✅ 有 | `speakers[]` 必填 |
| `service_minutes` | ✅ 有 | `speakers[]` 必填 |
| `fee` / `tax` | ✅ 有 | `speakers[]` 可选 |

**结论：** PPT 第 5/6 页对接 AI 需要的字段，**绝大部分已在你的请求/响应里**。缺的只有：

1. `period_name`（可用 `period_id` 代替）  
2. `other_fee`（业务费用，AI 可不收）  
3. 会议状态类字段（留在 PE，别塞进 AI 请求）

---

## 6. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-10-26 | 初版：按 PPT 第 5、6 页列名整理变量名，供对接；后续改 PPT 先改本文 |
| 2026-10-26 | 补 §5：与现有 schema 逐项核对 |
