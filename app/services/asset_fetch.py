"""按 s3_uri 取材料：优先本地映射；可选真 S3；PDF 渲第一页为 JPEG。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional, Tuple

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class FetchedObject:
    s3_uri: str
    content_type: str
    body: Optional[bytes] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    local_path: Optional[str] = None


def parse_s3_uri(s3_uri: str) -> Tuple[str, str]:
    if not s3_uri.startswith("s3://"):
        raise ValueError("invalid s3_uri: {0}".format(s3_uri))
    rest = s3_uri[5:]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError("invalid s3_uri: {0}".format(s3_uri))
    return bucket, key


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


def _fetch_real_s3(s3_uri: str, content_type: str) -> FetchedObject:
    settings = get_settings()
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        return FetchedObject(
            s3_uri=s3_uri,
            content_type=content_type,
            error_code="S3_NOT_FOUND",
            error_message="boto3 未安装，无法真读 S3（pip install boto3）",
        )

    bucket, key = parse_s3_uri(s3_uri)
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
                s3_uri=s3_uri,
                content_type=content_type,
                error_code="S3_CORRUPT",
                error_message="empty S3 object",
            )
        return FetchedObject(
            s3_uri=s3_uri,
            content_type=out_type,
            body=body,
        )
    except ClientError as e:
        code = (e.response or {}).get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return FetchedObject(
                s3_uri=s3_uri,
                content_type=content_type,
                error_code="S3_NOT_FOUND",
                error_message=str(e),
            )
        return FetchedObject(
            s3_uri=s3_uri,
            content_type=content_type,
            error_code="S3_CORRUPT",
            error_message=str(e),
        )
    except Exception as e:
        logger.exception("real s3 fetch failed %s", s3_uri)
        return FetchedObject(
            s3_uri=s3_uri,
            content_type=content_type,
            error_code="S3_CORRUPT",
            error_message=str(e),
        )


def fetch_object(s3_uri: str, content_type: str) -> FetchedObject:
    settings = get_settings()
    try:
        parse_s3_uri(s3_uri)
    except ValueError as e:
        return FetchedObject(
            s3_uri=s3_uri,
            content_type=content_type,
            error_code="ASSET_MISSING",
            error_message=str(e),
        )

    mapping = _load_map()
    rel = mapping.get(s3_uri)
    if rel:
        path = Path(rel)
        if not path.is_absolute():
            path = settings.asset_root / path
        if not path.exists():
            return FetchedObject(
                s3_uri=s3_uri,
                content_type=content_type,
                error_code="S3_NOT_FOUND",
                error_message="local file missing: {0}".format(path),
                local_path=str(path),
            )
        try:
            raw = path.read_bytes()
            if not raw:
                return FetchedObject(
                    s3_uri=s3_uri,
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
            return FetchedObject(
                s3_uri=s3_uri,
                content_type=out_type,
                body=body,
                local_path=str(path),
            )
        except Exception as e:
            logger.exception("fetch failed %s", s3_uri)
            return FetchedObject(
                s3_uri=s3_uri,
                content_type=content_type,
                error_code="S3_CORRUPT",
                error_message=str(e),
                local_path=str(path),
            )

    if settings.use_real_s3:
        return _fetch_real_s3(s3_uri, content_type)

    return FetchedObject(
        s3_uri=s3_uri,
        content_type=content_type,
        error_code="S3_NOT_FOUND",
        error_message="no local mapping for {0}".format(s3_uri),
    )
