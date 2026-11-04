# 模版 Pack 与 Crop 清单

## Pack 版本约定

| 字段 | 示例 | 说明 |
|------|------|------|
| template_pack_version | `2026Q2` | 请求 `refs.template_pack_version`；与 `ai.template_ref.version` 对齐 |
| 存储前缀 | `s3://pe-templates/{version}/` | 整图 + crops |
| 绑定 | 可按 `period_id` 覆盖通用版 | 二期手册/PPT 变更时新建 version，旧 job 可复现 |

建议目录：

```
s3://pe-templates/2026Q2/
  logo/bayer_logo.png
  lecture_hall/
    poster_full.jpg          # 从合格海报整图归档
    poster_header_crop.jpg
    poster_footer_wave_crop.jpg
    stand_full.jpg
    name_card_border_crop.jpg
    handbook_cover_current.jpg
    handbook_cover_stale_neg.jpg   # 负样本旧封面（若有）
    signin_template.jpg
  micro/
    ppt_intro_full.jpg
    ppt_intro_header_crop.jpg
    ppt_intro_footer_wave_crop.jpg
    ppt_agenda_full.jpg
    ppt_agenda_header_crop.jpg
    e_poster_full.png
    signin_template.jpg
  manifest.json
```

`manifest.json` 示例见 [templates/manifest.example.json](templates/manifest.example.json)。

---

## 药师大讲堂 — Crop 清单

源样例目录：`药师大讲堂/2-2026-4-17-河南美锐大药房连锁有限公司/`

| template_kind | 源文件 | Crop 目标 | crop_meta 建议 | 用途 |
|---------------|--------|-----------|----------------|------|
| POSTER | `1权益-海报.jpg` | 整图归档 | source=full | 版式比对基线 |
| POSTER | 同上 | 顶部标题区（含「菁英药师大讲堂」字标） | 约上 20% | OCR 标题 + 版式 |
| POSTER | 同上 | 底部青粉波浪装饰条 | 约下 15% | 模版特征匹配 |
| POSTER | 同上 | 主办/赞助红字区 | 底部文字带 | 辅助确认官方物料 |
| STAND | `2权益-展架.jpg` | 整图 + 与海报同款 footer/header crops | — | 展架版式与 Logo |
| NAME_CARD | `3台卡.jpg` | 单张台卡 ROI（4 张分别 crop） | 每卡一张 | OCR 姓名训练/评测 |
| NAME_CARD | 同上 | 台卡底部蓝绿装饰条 | 单卡下缘 | `NAME_CARD_TEMPLATE` |
| HANDBOOK | **缺失独立文件** | 需从 Teams/补拍：手册封面正面 | full cover | `HANDBOOK_DETECT` |
| HANDBOOK | 台卡图桌面手册仅作弱参考 | 不建议作主 ref | — | 正式以封面照为准 |
| LOGO_BAYER | 海报/展架角标 | Logo 外接矩形 | 紧裁 | `BAYER_LOGO` |
| SIGNIN | `9签到表-35（1）.jpg` 等 | 表头模版区（会议时间/时长栏） | 上半表头 | 模版一致性（可选） |
| SPEAKER_TITLE | `4讲者-高芳1.jpg` 等 `*1` | 课件标题条区域 | 投影/屏幕 ROI | `SPEAKER_TOPIC_OCR` 评测 |

台卡图中可见桌面白色手册叠放：仅证明「现场有手册物」，**不能替代** `HANDBOOK` 类型必传封面照。

---

## 微型药师 — Crop 清单

源样例：

- `微型药师/000090-2026-05-27-合肥市-老百姓大药房连锁（安徽）有限公司/`
- `微型药师/000089-2026-05-29-淮安广济医药连锁有限公司/`
- `微型药师/000125-2026-06-10-山西国大万民药房连锁有限公司/`

| template_kind | 推荐源文件 | Crop 目标 | 用途 |
|---------------|------------|-----------|------|
| PPT_INTRO | `000090/.../权益照片1.jpg`（或权益照片-1） | 投影画面「项目介绍」整页（透视矫正后） | `PPT_TEMPLATE_MATCH` + `PPT_PAGE_KIND` |
| PPT_INTRO | 同上 | 顶栏标题「项目介绍」 | 页类判定 |
| PPT_INTRO | 同上 | 底部彩色波浪装饰 | 模版特征 |
| PPT_INTRO | 同上 | 右上角圆形 Logo | `BAYER_LOGO` |
| PPT_AGENDA | `权益照片2` / 日程展示类 | 「电子日程/会议日程」投影页 | 第二页种类 |
| E_POSTER | `会议日程.png` / `.jpg` | 电子日程海报整图 | 关键字段 OCR 基线 |
| SIGNIN | `会议签到表.pdf` 首页渲染 | 表头标准栏位 | 模版/字段位置 |
| LOGO_BAYER | 投影页角标 | Logo crop | Logo 检测 |

透视说明：现场展示图常有倾角（如 000090 权益照片1）。入库 crop 应先做 **投影区域检测 → 透视矫正 → 再裁模版特征**，匹配时对查询图走同一流水线。

---

## crop_meta JSON 结构

写入 `ai.template_ref.crop_meta`：

```json
{
  "source_local_path": "药师大讲堂/2-2026-4-17-河南美锐大药房连锁有限公司/1权益-海报.jpg",
  "source_s3_uri": "s3://pe-templates/2026Q2/lecture_hall/poster_full.jpg",
  "coord_space": "normalized",
  "box": { "x": 0.0, "y": 0.85, "w": 1.0, "h": 0.15 },
  "note": "海报底部波浪装饰条",
  "preprocess": ["perspective_optional"]
}
```

`coord_space=normalized`：相对原图宽高 0~1，便于分辨率无关。

---

## Teams Folder 对齐

PPT/需求提到「照片示例在 Teams folder」。落地步骤：

1. 将 Teams 合格样例同步到本仓库或 S3 staging（与本地 `药师大讲堂/`、`微型药师/` 对齐）
2. 按上表产出 crops，上传 `s3://pe-templates/{version}/`
3. 跑脚本写入 `ai.template_ref`（或导入 `manifest.json`）
4. **补齐大讲堂手册封面独立照**（当前本地样例包缺失）
5. 若有旧版手册/旧 PPT，收入 `*_stale_neg` 供 `HANDBOOK_NOT_STALE` 标定

---

## 启用与切换

| 场景 | 行为 |
|------|------|
| 请求带 version | 只用该 version 且 `is_active` 或强制指定 |
| 请求不带 version | 用当期 period 绑定 pack，否则全局最新 active |
| 换期物料升级 | 新 version + 新 crops；旧会议重跑可钉死旧 version |
