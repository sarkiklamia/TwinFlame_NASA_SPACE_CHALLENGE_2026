"""Atomic JSON checkpoint helpers for Phase 09."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def load_watermark(path: str | Path) -> dict[str, Any] | None:
    checkpoint = Path(path)
    if not checkpoint.is_file():
        return None
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    if data.get("watermark_version") != 1:
        raise ValueError(f"Unsupported Phase 09 watermark: {checkpoint}")
    return data


def save_watermark(path: str | Path, data: dict[str, Any]) -> None:
    checkpoint = Path(path)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    temporary = checkpoint.with_name(checkpoint.name + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, checkpoint)
