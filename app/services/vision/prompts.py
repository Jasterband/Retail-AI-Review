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
    "store_names": string[]|null,
    "is_printed_form": boolean|null,
    "has_handwritten_signatures": boolean|null,
    "signin_template_ok": boolean|null,
    "header_complete": boolean|null,
    "rows_complete": boolean|null,
    "incomplete_row_count": number|null,
    "signin_complete_ok": boolean|null
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

NAME_CARD_FULL_PROMPT = """这是会议现场的【台卡/席卡整图】，桌上通常有 2~4 张印刷姓名台卡。
请直接读出画面中所有台卡上的中文姓名，返回严格 JSON（不要 markdown）：
{
  "name_card_names": string[]
}
规则：
- 只收人名（通常 2~4 个汉字）；去掉空格；不要职称/门店/英文；
- 尽量收齐全场可见台卡，常见 4 张；看不清的不要编造；
- 不要返回框坐标；不要把装饰图案、Logo 当成姓名。
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
        "TableCard": (
            "这是台卡整图。请直接读出桌上所有台卡印刷的中文姓名，"
            "写入 name_card_names（数组，常见 2~4 个）；不要编造；不做裁框。"
        ),
        "SpeakerTitle": (
            "这是讲者与课件标题合影。请抽取投影上的讲题标题（topic_title）、"
            "讲者姓名；日期/水印若有则抽。主题比对只在本类型做。"
        ),
        "SpeakerLecture": (
            "这是讲者授课现场照。只需确认画面清晰、为授课场景；"
            "不要抽取讲题标题、讲者姓名（topic_title / speaker_name_on_slide 填 null）；"
            "不做主题查重；水印若有则抽 watermark_*。"
        ),
        "Panorama": (
            "这是会场全景照片。请仔细数画面中【可见的人头/参会者】，"
            "含前排、侧排、后排，含讲者若在画面中；不要把椅子空位、投影人影、海报人像算进去。"
            "给出整数 people_count 与 people_count_confidence（0~1）。"
            "水印若有则抽 watermark_*。"
        ),
        "SignSheet": (
            "这是【打印出来的签到表】扫描/照片（可多页之一）：纸质打印表格，"
            "供参会者在姓名栏旁【手写签名】。"
            "请抽取：会议开始/结束时间、时长分钟；"
            "audience_count=本页可见听众签名行数（勿估全场总数；多页由上游累加）；"
            "听众所属门店名列表（若有）。"
            "模版判定：is_printed_form=是否为印刷签到表（含表头栏位+姓名/签名列）；"
            "has_handwritten_signatures=是否可见手写签字笔迹；"
            "signin_template_ok=是印刷签到表（有手签更好，空白表头也可 true）。"
            "截屏电子表、纯打印无签名栏、白纸乱写 → signin_template_ok=false。"
            "完整性核验（本页独立判，多页各自检）："
            "header_complete=本页若有表头区，则会议时间/时长/地点须已填写；"
            "纯续页无表头则 header_complete=null。"
            "rows_complete=凡已占用行（讲者签到+参会人员签到），"
            "姓名/职称/连锁名称/签名四列都须有内容；末尾空白模板行可不填。"
            "说明栏、其他/备注列不纳入必填。"
            "incomplete_row_count=缺列的已占用行数；"
            "signin_complete_ok=header_complete不为false 且 rows_complete=true。"
        ),
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
