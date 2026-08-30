from __future__ import annotations

import json
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
    MEDIA_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".ts"}

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
        candidates = [
            p for p in output_dir.rglob("*")
            if p.is_file()
            and aweme_id in p.stem
            and p.suffix.lower() in YtdlpService.MEDIA_EXTENSIONS
            and "-thumb" not in p.stem.lower()
            and not p.name.endswith((".part", ".ytdl", ".tmp"))
        ]
        return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0] if candidates else None

    @classmethod
    def is_media_file(cls, path: Path | None) -> bool:
        return bool(path and path.is_file() and path.suffix.lower() in cls.MEDIA_EXTENSIONS and "-thumb" not in path.stem.lower())

    def remove_archive_entry(self, aweme_id: str) -> None:
        """Remove one stale archive entry before an explicit missing-file retry."""
        if not self.archive_file.is_file():
            return
        try:
            lines = self.archive_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        kept = [line for line in lines if not line.split() or line.split()[-1] != str(aweme_id)]
        if kept == lines:
            return
        temporary = self.archive_file.with_suffix(self.archive_file.suffix + ".tmp")
        temporary.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        temporary.replace(self.archive_file)

    @staticmethod
    def public_metadata(info: dict[str, Any] | None) -> dict[str, Any]:
        """Return practical metadata and intentionally drop direct media URLs.

        yt-dlp may return ``None`` when an item is already present in the
        download archive, and some extractors can leave empty entries in
        ``requested_formats``.  Normalize both cases here so callers never
        fail with an opaque ``NoneType.get`` error.
        """
        if not isinstance(info, dict):
            return {}
        requested = [item for item in (info.get("requested_formats") or []) if isinstance(item, dict)]
        video = next((item for item in requested if item.get("vcodec") not in (None, "none")), info)
        audio = next((item for item in requested if item.get("acodec") not in (None, "none")), info)
        thumbnails = info.get("thumbnails") if isinstance(info.get("thumbnails"), list) else []
        thumbnail_urls = [
            item.get("url") for item in thumbnails
            if isinstance(item, dict) and isinstance(item.get("url"), str)
        ]
        if isinstance(info.get("thumbnail"), str) and info["thumbnail"] not in thumbnail_urls:
            thumbnail_urls.insert(0, info["thumbnail"])
        artists = info.get("artists")
        if isinstance(artists, list):
            artists_json = json.dumps([str(value) for value in artists], ensure_ascii=False)
        elif artists:
            artists_json = json.dumps([str(artists)], ensure_ascii=False)
        else:
            artists_json = None
        return {
            "id": str(info.get("id") or ""),
            "title": info.get("title"),
            "description": info.get("description"),
            "timestamp": info.get("timestamp"),
            "upload_date": info.get("upload_date"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
            "uploader_id": info.get("uploader_id"),
            "uploader_url": info.get("uploader_url"),
            "channel": info.get("channel"),
            "channel_id": info.get("channel_id"),
            "channel_url": info.get("channel_url"),
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "comment_count": info.get("comment_count"),
            "repost_count": info.get("repost_count"),
            "save_count": info.get("save_count"),
            "track": info.get("track"),
            "artists_json": artists_json,
            "album": info.get("album"),
            "availability": info.get("availability"),
            "thumbnail_url": thumbnail_urls[0] if thumbnail_urls else info.get("thumbnail"),
            "thumbnail_urls": thumbnail_urls,
            "format_id": info.get("format_id"),
            "width": video.get("width") or info.get("width"),
            "height": video.get("height") or info.get("height"),
            "fps": video.get("fps") or info.get("fps"),
            "vcodec": video.get("vcodec") or info.get("vcodec"),
            "acodec": audio.get("acodec") or info.get("acodec"),
            "filesize": info.get("filesize") or info.get("filesize_approx"),
            "container_ext": info.get("ext"),
        }

    def _opts(self, logger: _Logger, *, download: bool = False, output_template: str | None = None) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "cookiefile": str(self.cookie_file),
            "noplaylist": True,
            "http_headers": {"User-Agent": self.user_agent, "Referer": "https://www.douyin.com/"},
            "logger": logger,
            "quiet": True,
            "no_warnings": True,
            "windowsfilenames": True,
            "trim_file_name": 180,
        }
        if download:
            opts.update({
                "format": "bv*+ba/b",
                "merge_output_format": "mp4",
                "download_archive": str(self.archive_file),
                "outtmpl": {"default": output_template},
            })
        else:
            opts["skip_download"] = True
        return opts

    def extract_metadata(self, url: str, on_message: Callable[[str], None] | None = None) -> dict[str, Any]:
        logger = _Logger(on_message)
        try:
            with self.yt_dlp.YoutubeDL(self._opts(logger, download=False)) as ydl:
                info = ydl.extract_info(url, download=False)
            metadata = self.public_metadata(info)
            if not metadata:
                raise RuntimeError("yt-dlp 未返回视频元数据")
            return metadata
        except Exception as exc:
            if on_message:
                on_message(self._safe_message(str(exc)))
            raise

    def download_one(
        self,
        url: str,
        output_dir: Path,
        aweme_id: str,
        filename_prefix: str,
        on_progress: Callable[[dict[str, Any]], None],
        on_message: Callable[[str], None] | None = None,
        use_archive: bool = True,
    ) -> tuple[Path | None, dict[str, Any]]:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.archive_file.parent.mkdir(parents=True, exist_ok=True)

        def progress_hook(data: dict[str, Any] | None) -> None:
            if not isinstance(data, dict):
                return
            on_progress({
                "status": data.get("status"),
                "percent": data.get("_percent_str") or data.get("percent"),
                "speed": data.get("_speed_str") or data.get("speed"),
                "eta": data.get("_eta_str") or data.get("eta"),
                "filename": data.get("filename"),
            })

        template = str(output_dir / f"{filename_prefix}%(title)s [%(id)s].%(ext)s")
        opts = self._opts(_Logger(on_message), download=True, output_template=template)
        if not use_archive:
            opts.pop("download_archive", None)
        opts["progress_hooks"] = [progress_hook]
        def postprocessor_hook(data: dict[str, Any] | None) -> None:
            if not isinstance(data, dict):
                return
            on_progress({"status": f"postprocessing:{data.get('status', '')}", "filename": data.get("filepath") or data.get("filename")})

        opts["postprocessor_hooks"] = [postprocessor_hook]
        try:
            with self.yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            path = self._find_file(output_dir, aweme_id)
            metadata = self.public_metadata(info)
            # A download can be successful even when yt-dlp intentionally
            # returns no info dict (for example, an archive hit).  Preserve
            # the downloaded file and let the database's existing discovery
            # metadata fill in the missing fields.
            if not metadata:
                metadata = {"id": str(aweme_id)}
            return path, metadata
        except Exception as exc:
            if on_message:
                on_message(self._safe_message(str(exc)))
            raise
