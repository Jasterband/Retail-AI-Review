"""reason_code → 中文 comments（simple 响应后处理）。

检测点文案对齐根目录《按材料类型-图像检测清单_枚举检测点》检测点定义表。
"""

from __future__ import annotations

from typing import Optional

# 与枚举检测点 Excel / 对接文档 §7 对齐；ERROR 类码不写 comments
REASON_COMMENTS: dict[str, str] = {
    "ASSET_MISSING": "是否缺少必审材料或材料不可读",
    "OCR_LOW_CONFIDENCE": "文字/要素识别是否清晰可靠",
    "COMPOSITION_MISSING": "讲者和主题页PPT是否同时出现",

    "TEMPLATE_MISMATCH": "PPT模板特征是否与要求一致",
    "TEMPLATE_UNCERTAIN": "模版特征识别是否清晰可靠",
    "LOGO_MISSING": "是否有拜耳 Logo",
    "LOGO_UNCERTAIN": "拜耳 Logo 检出是否清晰可靠",
    "SPONSOR_MISSING": "图最下方是否出现赞助方「拜耳医药保健有限公司」",
    "SPONSOR_UNCERTAIN": "赞助方文案检出是否清晰可靠",
    "DATE_MISMATCH": "日期是否和表单一致",
    "TIME_MISMATCH": "时间是否和表单一致",
    "LOCATION_MISMATCH": "地点是否和表单一致",
    "SPEAKER_NAME_MISMATCH": "讲者姓名是否与表单一致",
    "TOPIC_MISMATCH": "标题是否和表单一致",
    "NAME_SET_MISMATCH": "姓名集合是否和表单一致",
    "COUNT_BELOW_THRESHOLD": "全景人数是否满足要求（大讲堂35人，微型药师单讲者6人，双讲者12人）",
    "COUNT_UNCERTAIN": "人数识别是否清晰可靠",
    "DURATION_BELOW_THRESHOLD": "会议时长是否满足条件（大讲堂120min，微型药师单讲者30min，双讲者60min）",
    "SIGNIN_INCOMPLETE": "签到表是否填写完整",
    "SIGNIN_COUNT_BELOW": "签到人数是否满足要求（大讲堂35人，微型药师单讲者6人，双讲者12人）",
    "HANDBOOK_NOT_FOUND": "是否存在菁英药师大讲堂宣传手册封面",
    "HANDBOOK_STALE": "手册是否为当期版本",
    "IMAGE_DUP": "本照片是否和其他场次照片重复",
}

# 系统 ERROR 相关码：simple 不附 comments（看顶层 error.message）
ERROR_REASON_CODES = frozenset(
    {
        "S3_NOT_FOUND",
        "S3_CORRUPT",
        "MODEL_TIMEOUT",
        "MODEL_UNAVAILABLE",
        "INTERNAL_ERROR",
    }
)


def comments_for_reason_code(
    reason_code: Optional[str],
    photo_type_name: Optional[str] = None,
    photo_type: Optional[str] = None,
) -> Optional[str]:
    if not reason_code:
        return None
    if reason_code in ERROR_REASON_CODES:
        return None
    if reason_code == "COMPOSITION_MISSING" and photo_type == "SpeakerLecture":
        text = "讲者与过程PPT是否同时出现"
    else:
        text = REASON_COMMENTS.get(reason_code) or f"审核未通过（{reason_code}）"
    name = (photo_type_name or "").strip()
    if name:
        return f"{name}：{text}"
    return text
