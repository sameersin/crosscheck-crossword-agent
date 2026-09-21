"""Decode and normalize bounded image uploads before any provider request."""

import io
import warnings

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError


def prepare_image(raw: bytes) -> bytes:
    """Decode, bound and re-encode actual image content; remove metadata before transmission."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("Use a PNG, JPEG, or WebP image.")
                if source.width * source.height > 16000000:
                    raise ValueError("Image is too large: maximum 16 million pixels.")
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((2400, 2400))
                target = io.BytesIO()
                image.save(target, format="PNG")
                return target.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("The uploaded file is not a valid supported image.") from exc


def read_uploaded_image(file: UploadFile, *, max_image_bytes: int) -> bytes:
    """Read a bounded upload and translate image validation into HTTP errors."""
    raw = file.file.read(max_image_bytes + 1)
    if len(raw) > max_image_bytes:
        raise HTTPException(413, "Image exceeds the configured upload limit.")
    try:
        return prepare_image(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
