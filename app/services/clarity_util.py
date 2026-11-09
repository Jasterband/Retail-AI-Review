"""本地图像清晰度（Laplacian 方差 → 0~1），不依赖 Vision。"""

from __future__ import annotations

import math
from io import BytesIO
from typing import Optional

import numpy as np
from PIL import Image

# 长边缩放上限：控制算力，同时保留足够细节
_MAX_SIDE = 1024
# sigmoid 中点：log10(var+1) ≈ log10(_MID_VAR) 时约 0.5
# 验收样清晰图 var 多在 170~2600；重度高斯模糊 (r≥8) 通常 <80
_MID_VAR = 80.0
_STEEP = 1.8


def laplacian_variance(image: Image.Image, max_side: int = _MAX_SIDE) -> float:
    """灰度图 3×3 Laplacian 方差；长边超过 max_side 时先等比缩小。"""
    gray = image.convert("L")
    w, h = gray.size
    m = max(w, h)
    if m > max_side:
        scale = max_side / float(m)
        gray = gray.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.BILINEAR,
        )
    arr = np.asarray(gray, dtype=np.float32)
    pad = np.pad(arr, 1, mode="edge")
    # [[0,1,0],[1,-4,1],[0,1,0]]
    lap = (
        pad[0:-2, 1:-1]
        + pad[1:-1, 0:-2]
        + pad[1:-1, 2:]
        + pad[2:, 1:-1]
        - 4.0 * pad[1:-1, 1:-1]
    )
    return float(lap.var())


def variance_to_score(
    variance: float,
    mid_var: float = _MID_VAR,
    steep: float = _STEEP,
) -> float:
    """将 Laplacian 方差映射到 0~1；越大越清晰。"""
    x = math.log10(max(0.0, variance) + 1.0)
    mid = math.log10(max(1e-6, mid_var))
    s = 1.0 / (1.0 + math.exp(-(x - mid) * steep))
    return round(min(1.0, max(0.0, s)), 4)


def compute_clarity_score(image_bytes: bytes) -> Optional[float]:
    """从图片字节计算清晰度 0~1；无法解码时返回 None。"""
    if not image_bytes:
        return None
    try:
        img = Image.open(BytesIO(image_bytes))
        img.load()
    except Exception:
        return None
    try:
        var = laplacian_variance(img)
        return variance_to_score(var)
    except Exception:
        return None
