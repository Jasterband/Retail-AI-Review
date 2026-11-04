"""图像感知哈希（纯 Pillow，无 scipy/ImageHash 依赖）。"""

from __future__ import annotations

from io import BytesIO
from typing import Optional

from PIL import Image


def _dct_1d(vector: list) -> list:
    """简易 DCT-II（8 点块用不到完整实现；对 32 向量足够）。"""
    import math

    n = len(vector)
    out = []
    for k in range(n):
        s = 0.0
        for i, x in enumerate(vector):
            s += x * math.cos((math.pi / n) * (i + 0.5) * k)
        out.append(s)
    return out


def compute_phash(image_bytes: bytes, hash_size: int = 8) -> Optional[str]:
    """pHash 近似：缩放到 32x32 → 灰度 → 2D DCT → 低频 → 中值二值化。"""
    try:
        import math

        img = Image.open(BytesIO(image_bytes)).convert("L").resize(
            (32, 32), Image.Resampling.LANCZOS
        )
        pixels = list(img.getdata())
        # row DCT
        rows = [pixels[r * 32 : (r + 1) * 32] for r in range(32)]
        dct_rows = [_dct_1d([float(x) for x in row]) for row in rows]
        # col DCT
        cols = [[dct_rows[r][c] for r in range(32)] for c in range(32)]
        dct = [_dct_1d(col) for col in cols]
        # transpose back: dct[c][r] → matrix[r][c]
        matrix = [[dct[c][r] for c in range(32)] for r in range(32)]
        block = [matrix[r][c] for r in range(hash_size) for c in range(hash_size)]
        # exclude DC
        vals = block[1:]
        med = sorted(vals)[len(vals) // 2]
        bits = "".join("1" if b > med else "0" for b in block)
        # to hex
        return "{:016x}".format(int(bits, 2))
    except Exception:
        return None


def phash_distance(a: str, b: str) -> int:
    try:
        x = int(a, 16) ^ int(b, 16)
        return bin(x).count("1")
    except Exception:
        return 999
