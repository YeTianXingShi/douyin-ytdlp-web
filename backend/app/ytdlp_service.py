from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class _Logger:
    def __init__(self, on_message: Callable[[str], None] | None = None):
        self.on_message = on_message

    def debug(self, message: str) -> None:
        if self.on_message and not message.startswith("[debug]"):
            self.on_message(message)

    info = debug

    def warning(self, message: str) -> None:
        if self.on_message:
            self.on_message(message)

    def error(self, message: str) -> None:
        if self.on_message:
            self.on_message(message)


class YtdlpService:
    def __init__(self, cookie_file: Path, archive_file: Path, user_agent: str):
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("yt-dlp package is unavailable; run uv sync") from exc
        self.yt_dlp = yt_dlp
        self.cookie_file = cookie_file
        self.archive_file = archive_file
        self.user_agent = user_agent

    @staticmethod
    def _safe_message(message: str) -> str:
        for marker in ("Cookie:", "cookie:", "Authorization:", "authorization:"):
            if marker in message:
                message = message.split(marker, 1)[0] + marker + " [redacted]"
        return message[:1000]

    @staticmethod
    def _find_file(output_dir: Path, aweme_id: str) -> Path | None:
        candidates = [p for p in output_dir.iterdir() if p.is_file() and aweme_id in p.stem and not p.name.endswith((".part", ".ytdl"))]
        return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0] if candidates else None

    def download_one(
        self,
        url: str,
        output_dir: Path,
        aweme_id: str,
        fallback_title: str | None,
        on_progress: Callable[[dict[str, Any]], None],
        on_message: Callable[[str], None] | None = None,
    ) -> Path | None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.archive_file.parent.mkdir(parents=True, exist_ok=True)

        def progress_hook(data: dict[str, Any]) -> None:
            on_progress({
                "status": data.get("status"),
                "percent": data.get("_percent_str") or data.get("percent"),
                "speed": data.get("_speed_str") or data.get("speed"),
                "eta": data.get("_eta_str") or data.get("eta"),
                "filename": data.get("filename"),
            })

        opts = {
            "cookiefile": str(self.cookie_file),
            "format": "bv*+ba/b",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "download_archive": str(self.archive_file),
            "outtmpl": {"default": str(output_dir / "%(title)s_%(upload_date)s_%(id)s.%(ext)s")},
            "windowsfilenames": True,
            "trim_file_name": 180,
            "http_headers": {"User-Agent": self.user_agent, "Referer": "https://www.douyin.com/"},
            "progress_hooks": [progress_hook],
            "logger": _Logger(on_message),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with self.yt_dlp.YoutubeDL(opts) as ydl:
                result = int(ydl.download([url]) or 0)
                if result:
                    raise RuntimeError(f"yt-dlp exited with code {result}")
            return self._find_file(output_dir, aweme_id)
        except Exception as exc:
            if on_message:
                on_message(self._safe_message(str(exc)))
            raise
