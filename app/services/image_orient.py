"""取图后按 EXIF Orientation 扶正像素，再送给 Vision / OCR。

手机竖拍常把展架/海报存成横像素 + Orientation=6/8；看图软件会自动转，
但把 JPEG 原字节直接 base64 给模型时多数会忽略 EXIF，模型看到的是侧放/倒放。
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional, Tuple

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# EXIF Orientation 需要旋/翻才与观看一致的取值（1=已正，可跳过重编码）
_NEEDS_TRANSFORM = {2, 3, 4, 5, 6, 7, 8}


def normalize_image_bytes(
    body: bytes,
    content_type: Optional[str] = None,
) -> Tuple[bytes, str, Optional[int]]:
    """
    若存在需处理的 EXIF Orientation，则旋正后重编码为 JPEG。

    Returns:
        (bytes, content_type, original_orientation_or_None)
        orientation 为 None 表示未读到或无需变换（原样返回）。
    """
    if not body:
        return body, content_type or "application/octet-stream", None

    mime = (content_type or "").split(";")[0].strip().lower()
    if mime == "application/pdf":
        return body, content_type or mime, None

    try:
        img = Image.open(BytesIO(body))
        img.load()
    except Exception:
        return body, content_type or "application/octet-stream", None

    orient = None
    try:
        orient = (img.getexif() or {}).get(274)
    except Exception:
        orient = None

    if orient not in _NEEDS_TRANSFORM:
        # 已是正向像素，或无 EXIF：不重编码，避免质量损失
        out_type = content_type or (
            "image/png" if (img.format or "").upper() == "PNG" else "image/jpeg"
        )
        return body, out_type, None

    try:
        fixed = ImageOps.exif_transpose(img)
        if fixed is None:
            fixed = img
        if fixed.mode not in ("RGB", "L"):
            fixed = fixed.convert("RGB")
        elif fixed.mode == "L":
            fixed = fixed.convert("RGB")
        buf = BytesIO()
        fixed.save(buf, format="JPEG", quality=92, optimize=True)
        out = buf.getvalue()
        logger.info(
            "applied EXIF orientation %s → upright (%sx%s → %sx%s)",
            orient,
            img.size[0],
            img.size[1],
            fixed.size[0],
            fixed.size[1],
        )
        return out, "image/jpeg", int(orient)
    except Exception:
        logger.exception("EXIF orientation normalize failed; using original bytes")
        return body, content_type or "image/jpeg", None
