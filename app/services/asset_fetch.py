"""按 file_url 取材料：优先本地映射；可选真 S3；PDF 渲第一页为 JPEG。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional, Tuple

from app.config import get_settings
from app.services.image_orient import normalize_image_bytes

logger = logging.getLogger(__name__)


@dataclass
class FetchedObject:
    file_url: str
    content_type: str
    body: Optional[bytes] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    local_path: Optional[str] = None
    # 原始 EXIF Orientation（2~8 表示已扶正重编码；None=无需或未处理）
    exif_orientation: Optional[int] = None


def parse_file_url(file_url: str) -> Tuple[str, str]:
    if not file_url.startswith("s3://"):
        raise ValueError("invalid file_url: {0}".format(file_url))
    rest = file_url[5:]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError("invalid file_url: {0}".format(file_url))
    return bucket, key


def _is_http_url(file_url: str) -> bool:
    return file_url.startswith("https://") or file_url.startswith("http://")


def _fetch_http(file_url: str, content_type: str) -> FetchedObject:
    try:
        import urllib.request

        req = urllib.request.Request(
            file_url,
            headers={"User-Agent": "retail-meeting-check/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            hdr = (resp.headers.get_content_type() or "").strip()
        if not raw:
            return FetchedObject(
                file_url=file_url,
                content_type=content_type,
                error_code="S3_CORRUPT",
                error_message="empty HTTP body",
            )
        out_type = content_type or hdr or "application/octet-stream"
        body = raw
        path_hint = file_url.split("?", 1)[0].lower()
        if out_type == "application/pdf" or path_hint.endswith(".pdf"):
            body = _pdf_first_page_jpeg(raw)
            out_type = "image/jpeg"
        body, out_type, exif_o = normalize_image_bytes(body, out_type)
        return FetchedObject(
            file_url=file_url,
            content_type=out_type,
            body=body,
            exif_orientation=exif_o,
        )
    except Exception as e:
        logger.exception("http fetch failed %s", file_url)
        msg = str(e)
        code = "S3_NOT_FOUND" if "404" in msg or "Not Found" in msg else "S3_CORRUPT"
        return FetchedObject(
            file_url=file_url,
            content_type=content_type,
            error_code=code,
            error_message=msg,
        )


def _load_map() -> Dict[str, str]:
    settings = get_settings()
    path = Path(settings.s3_local_map_path)
    if not path.is_absolute():
        path = settings.asset_root / path
    if not path.exists():
        logger.warning("s3 local map missing: %s", path)
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _pdf_first_page_jpeg(pdf_bytes: bytes) -> bytes:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_bytes)
    if len(doc) < 1:
        raise ValueError("empty PDF")
    page = doc[0]
    bitmap = page.render(scale=2)
    pil = bitmap.to_pil()
    buf = BytesIO()
    pil.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _fetch_real_s3(file_url: str, content_type: str) -> FetchedObject:
    settings = get_settings()
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        return FetchedObject(
            file_url=file_url,
            content_type=content_type,
            error_code="S3_NOT_FOUND",
            error_message="boto3 未安装，无法真读 S3（pip install boto3）",
        )

    bucket, key = parse_file_url(file_url)
    kwargs = {"region_name": settings.aws_region or None}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    client = boto3.client("s3", **{k: v for k, v in kwargs.items() if v})
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
        raw = obj["Body"].read()
        out_type = content_type or obj.get("ContentType") or "application/octet-stream"
        body = raw
        if out_type == "application/pdf" or key.lower().endswith(".pdf"):
            body = _pdf_first_page_jpeg(raw)
            out_type = "image/jpeg"
        if not body:
            return FetchedObject(
                file_url=file_url,
                content_type=content_type,
                error_code="S3_CORRUPT",
                error_message="empty S3 object",
            )
        body, out_type, exif_o = normalize_image_bytes(body, out_type)
        return FetchedObject(
            file_url=file_url,
            content_type=out_type,
            body=body,
            exif_orientation=exif_o,
        )
    except ClientError as e:
        code = (e.response or {}).get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return FetchedObject(
                file_url=file_url,
                content_type=content_type,
                error_code="S3_NOT_FOUND",
                error_message=str(e),
            )
        return FetchedObject(
            file_url=file_url,
            content_type=content_type,
            error_code="S3_CORRUPT",
            error_message=str(e),
        )
    except Exception as e:
        logger.exception("real s3 fetch failed %s", file_url)
        return FetchedObject(
            file_url=file_url,
            content_type=content_type,
            error_code="S3_CORRUPT",
            error_message=str(e),
        )


def fetch_object(file_url: str, content_type: str) -> FetchedObject:
    settings = get_settings()

    if _is_http_url(file_url):
        mapping = _load_map()
        rel = mapping.get(file_url)
        if rel:
            # 允许把 https URL 映射到本地样例
            path = Path(rel)
            if not path.is_absolute():
                path = settings.asset_root / path
            if path.exists():
                try:
                    raw = path.read_bytes()
                    out_type = content_type
                    body = raw
                    if content_type == "application/pdf" or path.suffix.lower() == ".pdf":
                        body = _pdf_first_page_jpeg(raw)
                        out_type = "image/jpeg"
                    body, out_type, exif_o = normalize_image_bytes(body, out_type)
                    return FetchedObject(
                        file_url=file_url,
                        content_type=out_type,
                        body=body,
                        local_path=str(path),
                        exif_orientation=exif_o,
                    )
                except Exception as e:
                    logger.exception("http-mapped local fetch failed %s", file_url)
                    return FetchedObject(
                        file_url=file_url,
                        content_type=content_type,
                        error_code="S3_CORRUPT",
                        error_message=str(e),
                        local_path=str(path),
                    )
        return _fetch_http(file_url, content_type)

    try:
        parse_file_url(file_url)
    except ValueError as e:
        return FetchedObject(
            file_url=file_url,
            content_type=content_type,
            error_code="ASSET_MISSING",
            error_message=str(e),
        )

    mapping = _load_map()
    rel = mapping.get(file_url)
    if rel:
        path = Path(rel)
        if not path.is_absolute():
            path = settings.asset_root / path
        if not path.exists():
            return FetchedObject(
                file_url=file_url,
                content_type=content_type,
                error_code="S3_NOT_FOUND",
                error_message="local file missing: {0}".format(path),
                local_path=str(path),
            )
        try:
            raw = path.read_bytes()
            if not raw:
                return FetchedObject(
                    file_url=file_url,
                    content_type=content_type,
                    error_code="S3_CORRUPT",
                    error_message="empty file",
                    local_path=str(path),
                )
            out_type = content_type
            body = raw
            if content_type == "application/pdf" or path.suffix.lower() == ".pdf":
                body = _pdf_first_page_jpeg(raw)
                out_type = "image/jpeg"
            body, out_type, exif_o = normalize_image_bytes(body, out_type)
            return FetchedObject(
                file_url=file_url,
                content_type=out_type,
                body=body,
                local_path=str(path),
                exif_orientation=exif_o,
            )
        except Exception as e:
            logger.exception("fetch failed %s", file_url)
            return FetchedObject(
                file_url=file_url,
                content_type=content_type,
                error_code="S3_CORRUPT",
                error_message=str(e),
                local_path=str(path),
            )

    if settings.use_real_s3:
        return _fetch_real_s3(file_url, content_type)

    return FetchedObject(
        file_url=file_url,
        content_type=content_type,
        error_code="S3_NOT_FOUND",
        error_message="no local mapping for {0}".format(file_url),
    )
