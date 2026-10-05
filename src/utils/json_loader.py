"""Shared utility for loading JSON asset data files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils.logger.logger import logger


def load_json_data(file_path: Path) -> list[dict[str, Any]]:
    """Loads and normalises JSON data containing asset lists or holdings.

    Accepts either a root list or a dict with an 'assets' key.
    Returns an empty list on missing file or parse error.
    """
    if not file_path.exists():
        logger.warning(f"File not found: {file_path}")
        return []

    try:
        with open(file_path, encoding="utf-8") as file:
            data: Any = json.load(file)
    except Exception as err:
        logger.error(f"Failed to read JSON file '{file_path}': {err}")
        return []

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and "assets" in data:
        raw_assets: Any = data.get("assets")
        if isinstance(raw_assets, list):
            return [item for item in raw_assets if isinstance(item, dict)]

    return []
