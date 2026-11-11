# 审核阈值表

默认值见 `app/services/thresholds.py`；请求 `options` 可覆盖。

| 参数 | 默认 | 用途 |
|------|------|------|
| `human_confidence_threshold` | 0.75 | 类型等置信度灰区门槛 |
| `watermark_time_skew_minutes` | 120 | 海报等材料上日程起止时间相对会议时段容差（**不做时间水印检测**） |
| `name_match_mode` | fuzzy | 讲者/台卡姓名比对 |
| `image_phash_max_distance` | 10 | IMAGE_DUP：有人物 / 手册等 pHash 汉明距离 ≤ 判盗用；**海报/电子海报/展架不适用**（仅 distance=0） |
| `image_similarity_threshold` | 0.92 | IMAGE_DUP：有人物 / 手册等 embedding 余弦 ≥ 判近似；**海报/电子海报/展架不做余弦** |
| `template_similarity_pass` | 0.85 | 台卡/权益模版 PASS |
| `template_similarity_fail` | 0.65 | 低于则 FAIL；中间灰区 UNCERTAIN |
| `ncc_hit_threshold` | 0.62 | 模版 NCC hit |
| `ncc_uncertain_threshold` | 0.52 | NCC 灰区下沿 |
| `panorama_count_min_confidence` | 0.70 | 人数置信度低于此 → UNCERTAIN |
| `panorama_need_lecture_hall` | 35 | 大讲堂全景合计人数 |
| `panorama_need_micro_single` | 6 | 微型单讲 |
| `panorama_need_micro_dual` | 12 | 微型双讲 |
| `signin_duration_lecture_hall` | 120 | 签到时长须 **超过** 此分钟数 |
| `signin_duration_micro_single` | 30 | 同上 |
| `signin_duration_micro_dual` | 60 | 同上 |
| `signin_audience_per_speaker` | 6 | 微型听众 ≥ 讲者×N |
| `logo_confidence_pass` | 0.55 | 微型 Logo vision 置信度 |
| `sponsor_confidence_pass` | 0.55 | 大讲堂赞助方文案 vision 置信度 |
