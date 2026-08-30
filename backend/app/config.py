from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _path_env(name: str, default: Path) -> Path:
    value = Path(os.getenv(name, str(default))).expanduser()
    # Relative values in .env are always rooted at the project directory,
    # regardless of whether uvicorn is launched from the repository root or
    # from backend/.
    if not value.is_absolute():
        value = PROJECT_ROOT / value
    return value.resolve()


def _app_version() -> str:
    configured = os.getenv("APP_VERSION")
    if configured:
        return configured.removeprefix("v")
    version_file = PROJECT_ROOT / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"


@dataclass(frozen=True)
class Settings:
    app_version: str = _app_version()
    cookie_file: Path = _path_env(
        "DOUYIN_COOKIE_FILE", PROJECT_ROOT / "secrets" / "douyin-cookies.txt"
    )
    download_root: Path = _path_env(
        "DOWNLOAD_ROOT", PROJECT_ROOT / "downloads"
    )
    state_dir: Path = _path_env("STATE_DIR", PROJECT_ROOT / "state")
    database_file: Path = _path_env(
        "DATABASE_FILE", PROJECT_ROOT / "state" / "jobs.sqlite3"
    )
    archive_file: Path = _path_env(
        "DOWNLOAD_ARCHIVE", PROJECT_ROOT / "state" / "download-archive.txt"
    )
    admin_token: str = os.getenv("ADMIN_TOKEN", "")
    user_agent: str = os.getenv(
        "DOUYIN_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    )
    proxy: str | None = os.getenv("DOUYIN_PROXY") or None
    request_delay: float = float(os.getenv("DOUYIN_REQUEST_DELAY", "1.0"))
    page_size: int = max(1, min(int(os.getenv("DOUYIN_PAGE_SIZE", "20")), 50))
    max_items: int = max(0, int(os.getenv("MAX_ITEMS", "10000")))
    request_timeout: float = float(os.getenv("DOUYIN_REQUEST_TIMEOUT", "20"))


settings = Settings()
