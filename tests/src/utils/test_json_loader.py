"""Unit tests for shared JSON loader utility in src/utils/json_loader.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.utils.json_loader import load_json_data


def test_load_json_data_file_not_found(tmp_path: Path) -> None:
    """Validates load_json_data returns empty list on missing file."""
    non_existent: Path = tmp_path / "missing.json"
    assert load_json_data(non_existent) == []


def test_load_json_data_invalid_json(tmp_path: Path) -> None:
    """Validates load_json_data handles corrupted JSON gracefully."""
    invalid_file: Path = tmp_path / "invalid.json"
    invalid_file.write_text("{broken_json: ", encoding="utf-8")
    assert load_json_data(invalid_file) == []


def test_load_json_data_read_exception(tmp_path: Path) -> None:
    """Validates load_json_data handles file read exception."""
    test_file: Path = tmp_path / "unreadable.json"
    test_file.write_text("{}", encoding="utf-8")
    with patch("builtins.open", side_effect=OSError("Read error")):
        assert load_json_data(test_file) == []


def test_load_json_data_list_format(tmp_path: Path) -> None:
    """Validates load_json_data reads direct list JSON structure."""
    valid_file: Path = tmp_path / "list.json"
    data: list[dict[str, Any]] = [{"symbol": "AAPL", "quantity": 10}]
    valid_file.write_text(json.dumps(data), encoding="utf-8")

    result: list[dict[str, Any]] = load_json_data(valid_file)
    assert len(result) == 1
    assert result[0]["symbol"] == "AAPL"


def test_load_json_data_assets_dict_format(tmp_path: Path) -> None:
    """Validates load_json_data reads dict with 'assets' key."""
    valid_file: Path = tmp_path / "dict.json"
    data: dict[str, Any] = {"assets": [{"symbol": "NVDA", "quantity": 5}]}
    valid_file.write_text(json.dumps(data), encoding="utf-8")

    result: list[dict[str, Any]] = load_json_data(valid_file)
    assert len(result) == 1
    assert result[0]["symbol"] == "NVDA"


def test_load_json_data_unexpected_types(tmp_path: Path) -> None:
    """Validates load_json_data returns empty list on invalid root types."""
    num_file: Path = tmp_path / "number.json"
    num_file.write_text("123", encoding="utf-8")
    assert load_json_data(num_file) == []
