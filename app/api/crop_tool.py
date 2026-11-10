"""四角点裁剪工具 API：列样例、透视变换、保存到 templates pack。"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from PIL import Image

from app.auth import require_token
from app.config import get_settings
from app.services.perspective import suggest_out_size, warp_quad

router = APIRouter(tags=["crop-tool"])

ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = ROOT / "docs" / "templates" / "2026Q2"

SAVE_PRESETS = [
    {
        "id": "equity1_ribbon",
        "label": "权益一 · 彩色丝带",
        "path": "micro/equity1_colorful_ribbon_crop.jpg",
    },
    {
        "id": "equity2_agenda",
        "label": "权益二 · 日程表",
        "path": "micro/equity2_agenda_table_crop.jpg",
    },
    {
        "id": "equity1_full",
        "label": "权益一 · 整页",
        "path": "micro/equity1_screen_full.jpg",
    },
    {
        "id": "equity2_full",
        "label": "权益二 · 整页",
        "path": "micro/equity2_screen_full.jpg",
    },
    {
        "id": "bayer_logo",
        "label": "拜耳 Logo",
        "path": "logo/bayer_logo.png",
    },
    {
        "id": "poster_key_fields",
        "label": "大讲堂 · 字段区(时间地点日程)",
        "path": "lecture_hall/poster_key_fields_crop.jpg",
    },
    {
        "id": "edm_key_fields",
        "label": "大讲堂 · 电子日程字段区",
        "path": "lecture_hall/edm_key_fields_crop.jpg",
    },
    {
        "id": "micro_edm_key_fields",
        "label": "微型 · 电子日程字段区",
        "path": "micro/edm_key_fields_crop.jpg",
    },
    {
        "id": "name_card_one",
        "label": "大讲堂 · 单张台卡（姓名定位用）",
        "path": "lecture_hall/name_card_one_roi.jpg",
    },
    {
        "id": "handbook_current",
        "label": "大讲堂 · 当期手册封面",
        "path": "lecture_hall/handbook_cover_current.jpg",
    },
    {
        "id": "handbook_stale",
        "label": "大讲堂 · 旧版手册负样本",
        "path": "lecture_hall/handbook_cover_stale_neg.jpg",
    },
]


class PointIn(BaseModel):
    x: float
    y: float


class WarpRequest(BaseModel):
    """points 顺序：左上 → 右上 → 右下 → 左下（原图像素坐标）。"""

    points: List[PointIn] = Field(min_length=4, max_length=4)
    sample_url: Optional[str] = None
    image_base64: Optional[str] = None
    out_width: Optional[int] = Field(default=None, ge=32, le=4000)
    out_height: Optional[int] = Field(default=None, ge=32, le=4000)
    save_as: Optional[str] = None
    format: Literal["jpeg", "png"] = "jpeg"

    @field_validator("save_as")
    @classmethod
    def safe_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.replace("\\", "/").lstrip("/")
        if ".." in v or v.startswith("/") or ":" in v:
            raise ValueError("非法 save_as")
        if not re.match(r"^[a-zA-Z0-9_./\-]+$", v):
            raise ValueError("save_as 仅允许字母数字路径")
        return v


def _resolve_sample(url: str) -> Path:
    """把 /samples/micro/... 映射到本地目录（零售照片ai审核/）。"""
    settings = get_settings()
    u = url.split("?", 1)[0]
    if u.startswith("/samples/micro/"):
        rel = u[len("/samples/micro/") :]
        path = settings.micro_samples_dir / rel
    elif u.startswith("/samples/hall/"):
        rel = u[len("/samples/hall/") :]
        path = settings.hall_samples_dir / rel
    else:
        raise HTTPException(status_code=400, detail="仅支持 /samples/micro|hall/ 样例")
    path = path.resolve()
    root = settings.sample_photos_root.resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(status_code=400, detail="路径越界")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="样例文件不存在")
    return path


def _load_image(body: WarpRequest) -> Image.Image:
    if body.sample_url:
        path = _resolve_sample(body.sample_url)
        return Image.open(path).convert("RGB")
    if body.image_base64:
        raw = body.image_base64
        if "," in raw:
            raw = raw.split(",", 1)[1]
        data = base64.b64decode(raw)
        return Image.open(io.BytesIO(data)).convert("RGB")
    raise HTTPException(status_code=400, detail="需要 sample_url 或 image_base64")


def _list_images(base: Path, url_prefix: str) -> List[dict]:
    out = []
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*")):
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        rel = p.relative_to(base).as_posix()
        out.append(
            {
                "label": rel,
                "url": "{0}/{1}".format(url_prefix.rstrip("/"), rel),
            }
        )
    return out


@router.get("/v1/crop/presets")
def crop_presets(_: str = Depends(require_token)):
    return {"presets": SAVE_PRESETS, "pack_dir": "docs/templates/2026Q2"}


@router.get("/v1/crop/samples")
def crop_samples(_: str = Depends(require_token)):
    settings = get_settings()
    micro = _list_images(settings.micro_samples_dir, "/samples/micro")
    hall = _list_images(settings.hall_samples_dir, "/samples/hall")
    # 微型权益 / 海报类优先排前
    def score(item: dict) -> tuple:
        lab = item["label"]
        pri = 0 if ("权益" in lab or "项目介绍" in lab or "电子日程" in lab) else (
            1 if "会议日程" in lab else 2
        )
        return (pri, lab)

    micro_sorted = sorted(micro, key=score)
    return {"micro": micro_sorted, "hall": hall}


@router.post("/v1/crop/warp")
def crop_warp(body: WarpRequest, _: str = Depends(require_token)):
    img = _load_image(body)
    iw, ih = img.size
    quad: List[Tuple[float, float]] = []
    for p in body.points:
        if p.x < -2 or p.y < -2 or p.x > iw + 2 or p.y > ih + 2:
            raise HTTPException(status_code=400, detail="点坐标超出图像范围")
        quad.append((float(p.x), float(p.y)))

    if body.out_width and body.out_height:
        out_size = (body.out_width, body.out_height)
    else:
        out_size = suggest_out_size(quad)

    try:
        warped = warp_quad(img, quad, out_size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    fmt = body.format
    buf = io.BytesIO()
    saved_path = None
    if body.save_as:
        dest = (PACK_DIR / body.save_as).resolve()
        if not str(dest).startswith(str(PACK_DIR.resolve())):
            raise HTTPException(status_code=400, detail="只能保存到 templates/2026Q2")
        dest.parent.mkdir(parents=True, exist_ok=True)
        ext = dest.suffix.lower()
        if ext == ".png":
            warped.save(dest, format="PNG")
            fmt = "png"
        else:
            warped.convert("RGB").save(dest, format="JPEG", quality=92)
            fmt = "jpeg"
        saved_path = str(dest.relative_to(ROOT))

    if fmt == "png":
        warped.save(buf, format="PNG")
        media = "image/png"
    else:
        warped.convert("RGB").save(buf, format="JPEG", quality=92)
        media = "image/jpeg"

    headers = {
        "X-Out-Width": str(out_size[0]),
        "X-Out-Height": str(out_size[1]),
    }
    if saved_path:
        headers["X-Saved-Path"] = saved_path
    return Response(content=buf.getvalue(), media_type=media, headers=headers)
