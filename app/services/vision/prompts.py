"""按材料类型构造多模态分析 prompt。"""

from __future__ import annotations

SYSTEM = (
    "你是药师会零售会议材料审核助手。根据图片返回严格 JSON（不要 markdown）。"
    "不适用的字段填 null。"
    "材料类型已由上游声明，不要猜测或改写类型。"
    "清晰度由本地算法计算，无需也不要返回 clarity_score。"
)

SCHEMA_HINT = """
返回 JSON 字段：
{
  "has_bayer_logo": boolean|null,
  "logo_confidence": number|null,
  "handbook_ok": boolean|null,
  "handbook_year": number|null,
  "ocr_fields": {
    "meeting_date": string|null,
    "handbook_year": number|null,
    "start_time": string|null,
    "end_time": string|null,
    "meeting_location": string|null,
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
"""


KEY_FIELDS_ROI_PROMPT = """这是从会议材料（海报/展架/电子日程）上裁出的【会议时间/地点/日程表】区域。
请只抽取下列字段，返回严格 JSON（不要 markdown）：
{
  "meeting_date": string|null,
  "start_time": string|null,
  "end_time": string|null,
  "meeting_location": string|null,
  "speaker_names": string[]|null
}
规则：看不清填 null；不要编造；speaker_names 只要人名列表，去掉「全体」。
"""

NAME_CARD_ROI_PROMPT = """这是从会议现场裁出的【单张台卡/席卡】区域。
请只抽取台卡上印刷的中文姓名，返回严格 JSON（不要 markdown）：
{
  "name": string|null,
  "name_card_names": string[]|null
}
规则：
- name 为一张台卡上的主姓名（通常 2~4 个汉字）；
- name_card_names 与 name 一致时也可只填 [name]；
- 看不清填 null；不要编造；不要把装饰图案、Logo、英文当成姓名。
"""

NAME_CARD_LOCATE_PROMPT = """第一张图：单张台卡参考（白底中央大字姓名 + 底部蓝绿波浪装饰条）。
第二张图：现场桌面，上面通常有 2~4 张同类台卡。

请根据【第二张真实照片】目测每张台卡位置，只返回 JSON（不要 markdown）：
{"cards":[{"box_norm":{"x":number,"y":number,"w":number,"h":number},"name":string|null}]}

要求：
1) 必须有 cards 数组；禁止只返回单个 name
2) box_norm 是相对第二张图的归一化坐标（0~1），一张卡一个框，尽量贴边
3) 不同台卡的 box 不要重叠；常见是上排 2 张、下排 2 张
4) name 填该卡印刷中文姓名，看不清填 null；不要编造
5) 坐标必须来自第二张图实测，不要使用示例数字
"""


def user_prompt(photo_type: str, project_type: str) -> str:
    focus = {
        "Poster": "抽取日程海报上的日期、时间、地点、讲者姓名；是否有拜耳十字 Logo。",
        "Stand": "抽取展架上的日期、时间、地点、讲者；是否有拜耳 Logo。",
        "EDM": "电子日程海报：日期时间地点讲者；拜耳 Logo。",
        "EDMDisplay": (
            "微型「权益二」现场展示（日程页）。核心检测："
            "画面中的规定模版上是否有【日程表】（通常含时间/内容/人员等表格行列）；"
            "有则为 has_agenda_table=true，页类 AGENDA。"
            "底部也可能有彩色波浪丝带，但权益二以日程表为准。"
            "同时看拜耳 Logo、水印。"
        ),
        "ProjectIntro": (
            "微型「权益一」现场展示（项目介绍页）。核心检测："
            "规定模版底部是否有【彩色丝带/彩色波浪装饰条】"
            "（蓝绿黄橙粉等多色流畅丝带图形，非普通单色线）；"
            "有则为 has_colorful_ribbon=true，页类 PROJECT_INTRO。"
            "本页一般是大段项目介绍文字，通常没有会议日程表。"
            "同时看拜耳 Logo、水印。"
        ),
        "TableCard": "识别桌上所有台卡上的中文姓名列表；是否像规定台卡样式（白底+装饰条）。",
        "SpeakerTitle": "若有投影课件，抽取讲题标题、讲者姓名、日期；统计可见人数可选；水印。",
        "Panorama": (
            "这是会场全景照片。请仔细数画面中【可见的人头/参会者】，"
            "含前排、侧排、后排，含讲者若在画面中；不要把椅子空位、投影人影、海报人像算进去。"
            "给出整数 people_count 与 people_count_confidence（0~1）。"
            "水印若有则抽 watermark_*。"
        ),
        "SignSheet": "签到表：会议开始/结束时间、时长分钟、听众人数、听众所属门店名列表。",
        "Manual": (
            "本图已声明为宣传手册。判断是否为「菁英药师大讲堂」宣传手册封面"
            "（handbook_ok）；务必读取封面上的年份数字写入 handbook_year 与"
            "ocr_fields.handbook_year（如 2026）。"
        ),
    }.get(photo_type, "按声明类型抽取清晰度、可见文字与 Logo。")

    return (
        "项目类型: {pt}\n材料类型（PE 已声明，按此审核，勿改类型）: {dt}\n"
        "任务: {focus}\n{schema}"
    ).format(pt=project_type, dt=photo_type, focus=focus, schema=SCHEMA_HINT)
