"""Local image storage helpers for image generation responses."""

from __future__ import annotations

import base64
import os
import secrets
import time
from pathlib import Path
from typing import Optional


_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}


def _normalize_base64_payload(payload: str) -> str:
    data = (payload or "").strip()
    if "," in data and data.lower().startswith("data:image/"):
        _prefix, data = data.split(",", 1)
    return data.strip()


def _prune_old_files(image_dir: Path, max_images: int) -> None:
    if max_images <= 0:
        return

    files = []
    for entry in image_dir.iterdir():
        if not entry.is_file():
            continue
        try:
            files.append((entry, entry.stat().st_mtime))
        except OSError:
            continue

    files.sort(key=lambda item: item[1], reverse=True)
    for entry, _mtime in files[max_images:]:
        try:
            entry.unlink(missing_ok=True)
        except OSError:
            continue


def save_base64_image(
    base64_data: str,
    mime_type: Optional[str] = None,
    image_dir: str = "data/images",
    max_images: int = 10,
) -> str:
    """
    Persist a base64 encoded image to disk and return the filename.

    This is intentionally side-effectful and used by the OpenAI response converter.
    """
    normalized = _normalize_base64_payload(base64_data)
    if not normalized:
        raise ValueError("empty image payload")

    raw = base64.b64decode(normalized, validate=False)

    ext = _MIME_EXT.get((mime_type or "").lower(), "bin")
    ts_ms = int(time.time() * 1000)
    rand = secrets.token_hex(8)
    filename = f"{ts_ms}_{rand}.{ext}"

    target_dir = Path(image_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    path = target_dir / filename
    tmp_path = target_dir / f".{filename}.tmp"

    with open(tmp_path, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())

    tmp_path.replace(path)
    _prune_old_files(target_dir, int(max_images))
    return filename

