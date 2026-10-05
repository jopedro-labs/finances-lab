"""
Authentication module for Google Drive API integration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

from src.config import settings

SCOPES: list[str] = ["https://www.googleapis.com/auth/drive.file"]


def load_credentials_safe(file_path: str | Path) -> dict[str, Any]:
    """Safely loads a JSON credentials.json file, returning status dict on failure."""
    path: Path = Path(file_path)
    if not path.exists() or path.stat().st_size == 0:
        return {"status": "empty_or_missing"}

    try:
        with open(path, encoding="utf-8") as f:
            data: Any = json.load(f)
            if isinstance(data, dict):
                return data
            return {"status": "invalid_json"}
    except (json.JSONDecodeError, OSError):
        return {"status": "invalid_json"}


def get_google_service_credentials(
    credentials_path: str | Path | None = None,
    token_path: str | Path | None = None,
    headless: bool = False,
) -> Any:
    """Loads Google Drive OAuth2 or Service Account credentials securely from env,
    settings, or files.
    """
    sa_env: str | None = settings.gdrive_service_account_file
    if sa_env and Path(sa_env).exists():
        return ServiceAccountCredentials.from_service_account_file(
            sa_env, scopes=SCOPES
        )  # type: ignore[no-untyped-call]

    token_target: Path = Path(token_path) if token_path else settings.gdrive_token_file
    creds_target: Path = (
        Path(credentials_path)
        if credentials_path
        else settings.gdrive_client_secret_file
    )

    creds: Credentials | None = None

    if token_target.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(token_target), SCOPES
            )  # type: ignore[no-untyped-call]
        except Exception:
            creds = None

    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())  # type: ignore[no-untyped-call]
        except Exception:
            creds = None

    if creds and creds.valid:
        return creds

    if headless:
        raise PermissionError("Authentication required but headless mode is on.")

    if not creds_target.exists():
        raise FileNotFoundError(f"Missing client secrets at {creds_target}")

    flow: InstalledAppFlow = InstalledAppFlow.from_client_secrets_file(
        str(creds_target), SCOPES
    )
    creds = flow.run_local_server(port=0)
    token_target.parent.mkdir(parents=True, exist_ok=True)
    with open(token_target, "w", encoding="utf-8") as token_file:
        token_file.write(creds.to_json())

    return creds


get_gdrive_credentials = get_google_service_credentials
