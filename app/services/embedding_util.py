"""轻量图像 embedding（纯 Pillow，无额外 ML 依赖）。

用于 IMAGE_DUP 近似相似：压缩 / 轻微裁剪 / 轻度调色后仍可能命中。
强液化、大幅裁切主体仍可能漏检（需更强模型时再换 CLIP 等）。
"""

from __future__ import annotations

import math
import struct
from io import BytesIO
from typing import List, Optional, Sequence

from PIL import Image


# 灰度缩略图边长 + RGB 每通道直方图桶数
_THUMB = 24
_HIST_BINS = 16
# 向量维：24*24 + 16*3 = 624
_DIM = _THUMB * _THUMB + _HIST_BINS * 3


def _l2_normalize(vec: List[float]) -> List[float]:
    s = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / s for x in vec]


def compute_image_embedding(image_bytes: bytes) -> Optional[bytes]:
    """生成 L2 归一化浮点向量并打包为 bytes（float32 LE）。"""
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        thumb = img.resize((_THUMB, _THUMB), Image.Resampling.LANCZOS)
        gray = thumb.convert("L")
        pixels = [p / 255.0 for p in gray.getdata()]

        # 全局 RGB 直方图（对压缩、轻度曝光更稳）
        hist: List[float] = []
        for ch in range(3):
            channel = list(thumb.getdata(ch))
            buckets = [0] * _HIST_BINS
            for v in channel:
                buckets[min(_HIST_BINS - 1, v * _HIST_BINS // 256)] += 1
            total = float(len(channel)) or 1.0
            hist.extend(c / total for c in buckets)

        vec = _l2_normalize(pixels + hist)
        return struct.pack("<{0}f".format(len(vec)), *vec)
    except Exception:
        return None


def unpack_embedding(blob: Optional[bytes]) -> Optional[List[float]]:
    if not blob:
        return None
    n = len(blob) // 4
    if n <= 0 or len(blob) != n * 4:
        return None
    try:
        return list(struct.unpack("<{0}f".format(n), blob))
    except struct.error:
        return None


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def embedding_similarity(a_blob: Optional[bytes], b_blob: Optional[bytes]) -> Optional[float]:
    a = unpack_embedding(a_blob)
    b = unpack_embedding(b_blob)
    if a is None or b is None:
        return None
    # 维度不一致（旧数据）无法比
    if len(a) != len(b):
        return None
    return cosine_similarity(a, b)
