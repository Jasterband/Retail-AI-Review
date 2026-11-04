"""按材料类型构造多模态分析 prompt。"""

from __future__ import annotations

SYSTEM = (
    "你是药师会零售会议材料审核助手。根据图片返回严格 JSON（不要 markdown）。"
    "不适用的字段填 null。clarity_score 为 0~1；detected_type 用英文枚举。"
)

SCHEMA_HINT = """
返回 JSON 字段：
{
  "clarity_score": number,
  "detected_type": string|null,
  "type_confidence": number,
  "has_bayer_logo": boolean|null,
  "logo_confidence": number|null,
  "handbook_ok": boolean|null,
  "handbook_year": number|null,
  "ocr_fields": {
    "meeting_date": string|null,
    "handbook_year": number|null,
    "start_time": string|null,
    "end_time": string|null,
    "location": string|null,
    "chain_or_store_name": string|null,
    "speaker_names": string[]|null,
    "topic_title": string|null,
    "speaker_name_on_slide": string|null,
    "watermark_date": string|null,
    "watermark_time": string|null,
    "watermark_location": string|null,
    "has_watermark": boolean|null
  },
  "people_count": number|null,
  "people_count_confidence": number|null,
  "name_card_names": string[]|null,
  "is_standard_name_card_style": boolean|null,
  "name_card_style_confidence": number|null,
  "ppt_page_kind": "PROJECT_INTRO"|"AGENDA"|"OTHER"|null,
  "ppt_template_match": boolean|null,
  "ppt_template_confidence": number|null,
  "has_colorful_ribbon": boolean|null,
  "colorful_ribbon_confidence": number|null,
  "has_agenda_table": boolean|null,
  "agenda_table_confidence": number|null,
  "signin": {
    "start_time": string|null,
    "end_time": string|null,
    "duration_minutes": number|null,
    "audience_count": number|null,
    "store_names": string[]|null
  }|null
}
detected_type 可选: E_POSTER, POSTER, STAND, NAME_CARD, HANDBOOK, SPEAKER_PHOTO,
PANORAMA, SIGNIN, E_POSTER_DISPLAY, PROJECT_INTRO_DISPLAY
"""


def user_prompt(declared_type: str, project_type: str) -> str:
    focus = {
        "POSTER": "抽取日程海报上的日期、时间、地点、讲者姓名；是否有拜耳十字 Logo。",
        "STAND": "抽取展架上的日期、时间、地点、讲者；是否有拜耳 Logo。",
        "E_POSTER": "电子日程海报：日期时间地点讲者；拜耳 Logo。",
        "E_POSTER_DISPLAY": (
            "微型「权益二」现场展示（日程页）。核心检测："
            "画面中的规定模版上是否有【日程表】（通常含时间/内容/人员等表格行列）；"
            "有则为 has_agenda_table=true，页类 AGENDA。"
            "底部也可能有彩色波浪丝带，但权益二以日程表为准。"
            "同时看拜耳 Logo、水印。"
        ),
        "PROJECT_INTRO_DISPLAY": (
            "微型「权益一」现场展示（项目介绍页）。核心检测："
            "规定模版底部是否有【彩色丝带/彩色波浪装饰条】"
            "（蓝绿黄橙粉等多色流畅丝带图形，非普通单色线）；"
            "有则为 has_colorful_ribbon=true，页类 PROJECT_INTRO。"
            "本页一般是大段项目介绍文字，通常没有会议日程表。"
            "同时看拜耳 Logo、水印。"
        ),
        "NAME_CARD": "识别桌上所有台卡上的中文姓名列表；是否像规定台卡样式（白底+装饰条）。",
        "SPEAKER_PHOTO": "若有投影课件，抽取讲题标题、讲者姓名、日期；统计可见人数可选；水印。",
        "PANORAMA": (
            "这是会场全景照片。请仔细数画面中【可见的人头/参会者】，"
            "含前排、侧排、后排，含讲者若在画面中；不要把椅子空位、投影人影、海报人像算进去。"
            "给出整数 people_count 与 people_count_confidence（0~1）。"
            "水印若有则抽 watermark_*。"
        ),
        "SIGNIN": "签到表：会议开始/结束时间、时长分钟、听众人数、听众所属门店名列表。",
        "HANDBOOK": (
            "是否为「菁英药师大讲堂」宣传手册封面（handbook_ok）；"
            "务必读取封面上的年份数字写入 handbook_year 与 ocr_fields.handbook_year"
            "（如 2026）；detected_type=HANDBOOK。"
        ),
    }.get(declared_type, "尽量抽取清晰度、类型、可见文字与 Logo。")

    return (
        "项目类型: {pt}\n声明材料类型: {dt}\n任务: {focus}\n{schema}"
    ).format(pt=project_type, dt=declared_type, focus=focus, schema=SCHEMA_HINT)
