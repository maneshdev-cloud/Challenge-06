"""Streaming upload guardrails, pixel-bomb protection, EXIF stripping, and compression."""

from __future__ import annotations

import io
import warnings

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

__all__ = [
    "ALLOWED_IMAGE_FORMATS",
    "ALLOWED_UPLOAD_MIMES",
    "MAX_ROOM_IMAGE_BYTES",
    "read_room_upload_bytes",
    "validate_and_optimize_room_image",
]

MAX_ROOM_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
ALLOWED_UPLOAD_MIMES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "application/octet-stream",
}
Image.MAX_IMAGE_PIXELS = 25_000_000


async def read_room_upload_bytes(file: UploadFile) -> bytes:
    """Stream uploaded room photo chunks up to 5 MB and validate MIME/non-empty content."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_ROOM_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Image is larger than the 5 MB limit. Please upload a photo under 5 MB.",
            )
        chunks.append(chunk)

    raw_bytes = b"".join(chunks)
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image file is empty.")
    if file.content_type and file.content_type.lower() not in ALLOWED_UPLOAD_MIMES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported image format. Please upload JPG, PNG, or WebP (max 5 MB).",
        )
    return raw_bytes


def _reencode_clean_image(raw_bytes: bytes, fmt: str, mime_type: str) -> tuple[bytes, str]:
    """Re-encode image without EXIF metadata, shrinking large uploads to max 1280 px."""
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img.load()
        out = io.BytesIO()
        if len(raw_bytes) > 1_200_000 or max(img.size) > 1280:
            rgb = img.convert("RGB")
            rgb.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            rgb.save(out, format="JPEG", quality=84, optimize=True)
            return out.getvalue(), "image/jpeg"

        target_mode = "RGBA" if img.mode in {"RGBA", "LA", "P"} and fmt != "JPEG" else "RGB"
        clean_img = img.convert(target_mode)
        if fmt == "PNG":
            clean_img.save(out, format="PNG")
        else:
            clean_img.save(out, format=fmt, quality=88)
        return out.getvalue(), mime_type


def validate_and_optimize_room_image(raw_bytes: bytes) -> tuple[bytes, str]:
    """Verify JPG/PNG/WebP integrity, bound pixels, strip EXIF tags, and shrink huge files."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(raw_bytes)) as img:
                fmt = (img.format or "").upper()
                width, height = img.size
                img.verify()
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise HTTPException(
                status_code=415,
                detail="Invalid or oversized image. Upload a valid JPG, PNG, or WebP photo.",
            ) from exc

        if fmt not in ALLOWED_IMAGE_FORMATS:
            raise HTTPException(
                status_code=415,
                detail="Unsupported image format. Please upload JPG, PNG, or WebP (max 5 MB).",
            )
        if width * height > 25_000_000:
            raise HTTPException(
                status_code=415,
                detail="Image dimensions exceed safe pixel limit. Upload a smaller photo.",
            )
        try:
            return _reencode_clean_image(raw_bytes, fmt, ALLOWED_IMAGE_FORMATS[fmt])
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise HTTPException(
                status_code=415,
                detail="Corrupted image data. Upload a valid JPG, PNG, or WebP photo.",
            ) from exc
