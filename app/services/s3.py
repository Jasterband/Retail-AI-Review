"""S3 读取：开发期委托本地映射（asset_fetch）。"""

from __future__ import annotations

from app.services.asset_fetch import FetchedObject, fetch_object, parse_s3_uri

__all__ = ["FetchedObject", "fetch_object", "parse_s3_uri"]
