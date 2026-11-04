"""四角点透视变换（Pillow PERSPECTIVE）。"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from PIL import Image


Point = Tuple[float, float]


def _solve_8(matrix: List[List[float]], rhs: List[float]) -> List[float]:
    """高斯消元解 8x8。"""
    n = 8
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("四点共线或退化，无法透视变换")
        a[col], a[pivot] = a[pivot], a[col]
        div = a[col][col]
        for j in range(col, n + 1):
            a[col][j] /= div
        for i in range(n):
            if i == col:
                continue
            factor = a[i][col]
            for j in range(col, n + 1):
                a[i][j] -= factor * a[col][j]
    return [a[i][n] for i in range(n)]


def perspective_coeffs(
    src_quad: Sequence[Point],
    dst_quad: Sequence[Point],
) -> Tuple[float, ...]:
    """
    求 Pillow Image.Transform.PERSPECTIVE 的 8 系数。
    映射：输出图坐标 → 原图坐标。
    src_quad / dst_quad：各 4 点，顺序 TL, TR, BR, BL。
    """
    if len(src_quad) != 4 or len(dst_quad) != 4:
        raise ValueError("需要恰好 4 个点")
    matrix: List[List[float]] = []
    rhs: List[float] = []
    for (x, y), (u, v) in zip(dst_quad, src_quad):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rhs.append(u)
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.append(v)
    return tuple(_solve_8(matrix, rhs))


def warp_quad(
    image: Image.Image,
    src_quad: Sequence[Point],
    out_size: Tuple[int, int],
) -> Image.Image:
    """将原图四边形区域透视拉成 out_size 矩形。"""
    w, h = out_size
    if w < 8 or h < 8:
        raise ValueError("输出尺寸过小")
    dst = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
    coeffs = perspective_coeffs(src_quad, dst)
    return image.transform(
        (w, h),
        Image.Transform.PERSPECTIVE,
        coeffs,
        Image.Resampling.BICUBIC,
    )


def suggest_out_size(src_quad: Sequence[Point], max_side: int = 1200) -> Tuple[int, int]:
    """按四边形边长估算输出宽高。"""
    def dist(a: Point, b: Point) -> float:
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    top = dist(src_quad[0], src_quad[1])
    bottom = dist(src_quad[3], src_quad[2])
    left = dist(src_quad[0], src_quad[3])
    right = dist(src_quad[1], src_quad[2])
    w = max(top, bottom)
    h = max(left, right)
    scale = min(1.0, max_side / max(w, h, 1.0))
    return max(32, int(round(w * scale))), max(32, int(round(h * scale)))
