# 模版 Pack 投放说明（2026Q2）

审核流水线会加载本目录参考图，做 **NCC 模版匹配 +（Logo/台卡/手册）视觉对照**。

---

## 已就绪 ✅

| 路径 | 用途 |
|------|------|
| `logo/bayer_logo.png` | 官方 Bayer Cross → `BAYER_LOGO` |
| `micro/equity1_colorful_ribbon_crop.jpg` | 权益一彩色丝带 → `PPT_TEMPLATE_MATCH` |
| `micro/equity1_screen_full.jpg` | 权益一整页（对照） |
| `micro/equity2_agenda_table_crop.jpg` | 权益二日程表 → `PPT_TEMPLATE_MATCH` |
| `micro/equity2_screen_full.jpg` | 权益二整页（对照） |
| `lecture_hall/poster_footer_wave_crop.jpg` | 海报底波浪 → 旁证 / `poster_wave_match` |
| `lecture_hall/name_card_one_roi.jpg` | 单张台卡 → `NAME_CARD_TEMPLATE` |
| `lecture_hall/name_card_border_crop.jpg` | 台卡底边装饰条（加强） |
| `lecture_hall/handbook_cover_current.jpg` | 当期手册封面 → `HANDBOOK_DETECT` / `HANDBOOK_NOT_STALE` |

---

## 手册旧版判定（无负样本时）

不强制提供 `handbook_cover_stale_neg.jpg`。  
规则：OCR 封面年份须等于 `HANDBOOK_CURRENT_YEAR`（默认 **2026**）；否则 `HANDBOOK_NOT_STALE` FAIL。

四角点裁剪页：http://127.0.0.1:8000/crop/
