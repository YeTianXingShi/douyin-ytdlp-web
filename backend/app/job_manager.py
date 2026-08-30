from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from .config import Settings
from .cookie_provider import CookieProvider
from .db import JobDB, utc_now
from .jellyfin import (
    download_image,
    episode_stem,
    safe_component,
    single_media_dir,
    write_episode_nfo,
    write_movie_nfo,
    write_profile_nfo,
    write_season_nfo,
)
from .profile_service import IMAGE_TYPES, VIDEO_TYPES, DouyinPost, ProfileService
from .schemas import CurrentItem, JobItem, JobStatus, ProfilePost, ProfileSummary, RefreshItem, RefreshSummary
from .ytdlp_service import YtdlpService


def _safe_error(error: str) -> str:
    error = re.sub(r"(?i)(cookie|authorization)\s*[:=]\s*[^\s;]+", r"\1=[redacted]", error)
    return error[:1000]


def _error_code(message: str) -> str:
    value = message.lower()
    if "cookie" in value or "login" in value or "sign in" in value:
        return "login_required"
    if "429" in value or "rate limit" in value:
        return "rate_limited"
    if "not found" in value or "404" in value:
        return "not_found"
    if "permission" in value or "forbidden" in value:
        return "forbidden"
    if "unsupported" in value:
        return "unsupported"
    return "download_error"


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = JobDB(settings.database_file)
        self.cookies = CookieProvider(settings.cookie_file)
        self.profile = ProfileService(settings, self.cookies)
        self.ytdlp = YtdlpService(settings.cookie_file, settings.archive_file, settings.user_agent)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker_task: asyncio.Task[None] | None = None

    async def _save_profile_artwork(self, profile: Any) -> None:
        try:
            urls = await self.profile.fetch_profile_artwork(profile["sec_user_id"])
        except Exception:
            return
        if not urls:
            return
        image, _ = await asyncio.to_thread(
            download_image,
            urls,
            self.settings.download_root / profile["media_dir"] / "poster",
            {"User-Agent": self.settings.user_agent, "Referer": "https://www.douyin.com/"},
            self.settings.request_timeout,
        )
        if image:
            self.db.update_profile_metadata(profile["id"], poster_file=str(image.relative_to(self.settings.download_root)))

    async def start(self) -> None:
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.settings.download_root.mkdir(parents=True, exist_ok=True)
        for job_id in self.db.recover_running():
            await self.queue.put(job_id)
        self.worker_task = asyncio.create_task(self._worker(), name="douyin-download-worker")

    async def stop(self) -> None:
        if self.worker_task:
            self.worker_task.cancel()
            await asyncio.gather(self.worker_task, return_exceptions=True)

    @staticmethod
    def _dt(value: str | None) -> str | None:
        return value

    def profile_summary(self, row) -> dict[str, Any]:
        result = dict(row)
        result.update(self.db.profile_stats(row["id"]))
        pending = self.db.pending_refresh(row["id"])
        result["pending_refresh_id"] = pending["id"] if pending else None
        return result

    def list_profiles(self) -> list[dict[str, Any]]:
        return [self.profile_summary(row) for row in self.db.list_profiles()]

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        row = self.db.profile_by_id(profile_id)
        if not row:
            raise KeyError(profile_id)
        return self.profile_summary(row)

    async def add_profile(self, source_url: str) -> dict[str, Any]:
        sec_user_id = await self.profile.resolve_sec_user_id(source_url)
        existing = self.db.profile_by_sec_id(sec_user_id)
        if existing:
            if not existing["display_name"]:
                display_name = await self.profile.fetch_profile_name(sec_user_id)
                if display_name:
                    self.db.update_profile_display_name(existing["id"], display_name)
                    existing = self.db.profile_by_id(existing["id"]) or existing
                    write_profile_nfo(existing, self.settings.download_root / existing["media_dir"] / "tvshow.nfo")
            if not existing["poster_file"]:
                await self._save_profile_artwork(existing)
            return self.profile_summary(existing)
        display_name = await self.profile.fetch_profile_name(sec_user_id)
        created = self.db.create_profile(sec_user_id, source_url, display_name)
        write_profile_nfo(created, self.settings.download_root / created["media_dir"] / "tvshow.nfo")
        await self._save_profile_artwork(created)
        return self.profile_summary(created)

    def delete_profile(self, profile_id: str) -> None:
        if not self.db.delete_profile(profile_id):
            raise KeyError(profile_id)

    async def refresh_profile(self, profile_id: str, max_items: int = 0, time_range: str = "all") -> str:
        profile = self.db.profile_by_id(profile_id)
        if not profile:
            raise KeyError(profile_id)
        active = self.db.active_refresh(profile_id)
        if active:
            return active["id"]
        pending = self.db.pending_refresh(profile_id)
        if pending:
            return pending["id"]
        job_id = self.db.create_job("refresh", profile_id=profile_id, max_items=max_items or self.settings.max_items, time_range=time_range)
        refresh_id = self.db.create_refresh(profile_id, job_id, time_range=time_range)
        await self.queue.put(job_id)
        return refresh_id

    async def create_legacy_job(self, source_url: str, mode: str, max_items: int = 0) -> str:
        if mode == "user_posts":
            profile = await self.add_profile(source_url)
            refresh_id = await self.refresh_profile(profile["id"], max_items, "all")
            refresh = self.db.get_refresh(refresh_id)
            return refresh["job_id"]
        aweme_id = await self._single_id(source_url)
        job_id = self.db.create_job("download")
        self.db.add_job_items(job_id, [{"aweme_id": aweme_id, "video_url": f"https://www.douyin.com/video/{aweme_id}", "title": None, "status": "queued"}])
        await self.queue.put(job_id)
        return job_id

    def refresh_summary(self, refresh_id: str) -> dict[str, Any]:
        row = self.db.get_refresh(refresh_id)
        if not row:
            raise KeyError(refresh_id)
        return dict(row)

    def refresh_items(self, refresh_id: str) -> list[dict[str, Any]]:
        if not self.db.get_refresh(refresh_id):
            raise KeyError(refresh_id)
        return [dict(row) for row in self.db.list_refresh_items(refresh_id)]

    def apply_refresh(self, profile_id: str, refresh_id: str, selected_ids: list[str]) -> dict[str, Any]:
        refresh = self.db.get_refresh(refresh_id)
        if not refresh or refresh["profile_id"] != profile_id:
            raise KeyError(refresh_id)
        result = dict(self.db.apply_refresh(refresh_id, selected_ids))
        profile = self.db.profile_by_id(profile_id)
        if profile:
            profile_dir = self.settings.download_root / profile["media_dir"]
            write_profile_nfo(profile, profile_dir / "tvshow.nfo")
            for row in self.db.list_posts(profile_id, "all"):
                if row["season_number"] is not None:
                    season_dir = profile_dir / f"Season {int(row['season_number'])}"
                    write_season_nfo(profile, int(row["season_number"]), season_dir / "season.nfo")
                if row["nfo_file"]:
                    write_episode_nfo(profile, row, self.settings.download_root / row["nfo_file"])
        return result

    def posts(self, profile_id: str, status_filter: str = "all") -> list[dict[str, Any]]:
        if not self.db.profile_by_id(profile_id):
            raise KeyError(profile_id)
        result = []
        for row in self.db.list_posts(profile_id, status_filter):
            item = dict(row)
            media_file = row["media_file"] or row["download_file"]
            item["file_exists"] = YtdlpService.is_media_file(self.settings.download_root / media_file) if media_file else False
            result.append(item)
        return result

    async def create_download(self, profile_id: str, aweme_ids: list[str], retry_only: bool = False) -> str:
        if not self.db.profile_by_id(profile_id):
            raise KeyError(profile_id)
        job_id = self.db.create_job("download", profile_id=profile_id)
        items: list[dict[str, Any]] = []
        for aweme_id in dict.fromkeys(aweme_ids):
            post = self.db.get_post(profile_id, aweme_id)
            if not post:
                raise ValueError(f"作品不存在：{aweme_id}")
            status = "queued"
            item: dict[str, Any] = {"aweme_id": aweme_id, "video_url": post["video_url"], "title": post["title"], "status": status, "attempt_count": post["attempt_count"]}
            media_path = self.settings.download_root / (post["media_file"] or post["download_file"] or "")
            has_downloaded_media = post["download_status"] == "downloaded" and YtdlpService.is_media_file(media_path)
            if has_downloaded_media:
                item.update(status="already_downloaded", file_name=post["download_file"], skip_reason_code="already_downloaded", skip_reason_message="该作品已下载")
            elif post["download_status"] == "downloaded" and post["remote_state"] != "remote_missing":
                # Keep the database status visible as downloaded+missing in
                # the UI, but an explicit selection is allowed to repair the
                # stale record and bypass its old archive entry.
                self.ytdlp.remove_archive_entry(aweme_id)
                self.db.update_post(profile_id, aweme_id, download_status="queued", download_file=None, media_file=None, nfo_file=None, downloaded_at=None, media_title_at_download=None)
                item["status"] = "queued"
            elif post["remote_state"] == "remote_missing":
                item.update(status="skipped", skip_reason_code="remote_missing", skip_reason_message="作品已不在当前主页")
            elif post["download_status"] == "skipped":
                item.update(status="skipped", skip_reason_code=post["skip_reason_code"], skip_reason_message=post["skip_reason_message"])
            elif retry_only and post["download_status"] != "failed":
                raise ValueError(f"只能重试失败作品：{aweme_id}")
            elif not retry_only and post["download_status"] == "failed":
                item.update(status="skipped", skip_reason_code="retry_required", skip_reason_message="失败作品请使用重试操作")
            else:
                self.db.update_post(profile_id, aweme_id, download_status="queued", last_error_code=None, last_error_message=None)
            items.append(item)
        self.db.add_job_items(job_id, items)
        await self.queue.put(job_id)
        return job_id

    async def retry_posts(self, profile_id: str, aweme_ids: list[str]) -> str:
        for aweme_id in aweme_ids:
            post = self.db.get_post(profile_id, aweme_id)
            if not post or post["download_status"] != "failed":
                raise ValueError(f"只能重试失败作品：{aweme_id}")
            self.db.update_post(profile_id, aweme_id, download_status="queued", last_error_code=None, last_error_message=None)
        return await self.create_download(profile_id, aweme_ids, retry_only=True)

    async def create_metadata_refresh(self, profile_id: str, aweme_ids: list[str]) -> str:
        if not self.db.profile_by_id(profile_id):
            raise KeyError(profile_id)
        requested = list(dict.fromkeys(aweme_ids))
        posts = {row["aweme_id"]: row for row in self.db.list_posts(profile_id, "all")}
        if requested:
            missing = [aweme_id for aweme_id in requested if aweme_id not in posts]
            if missing:
                raise ValueError(f"作品不存在：{missing[0]}")
            selected = [posts[aweme_id] for aweme_id in requested]
        else:
            selected = [row for row in posts.values() if row["remote_state"] == "active" and row["aweme_type"] in VIDEO_TYPES]
        if not selected:
            raise ValueError("没有可刷新的视频作品")
        job_id = self.db.create_job("metadata", profile_id=profile_id)
        items = []
        for post in selected:
            if post["remote_state"] == "remote_missing":
                items.append({"aweme_id": post["aweme_id"], "video_url": post["video_url"], "title": post["title"], "status": "skipped", "skip_reason_code": "remote_missing", "skip_reason_message": "作品已不在当前主页"})
            elif post["aweme_type"] not in VIDEO_TYPES:
                items.append({"aweme_id": post["aweme_id"], "video_url": post["video_url"], "title": post["title"], "status": "skipped", "skip_reason_code": "unsupported", "skip_reason_message": "非视频作品不支持元数据刷新"})
            else:
                items.append({"aweme_id": post["aweme_id"], "video_url": post["video_url"], "title": post["title"], "status": "queued"})
        self.db.add_job_items(job_id, items)
        await self.queue.put(job_id)
        return job_id

    async def retry_metadata(self, profile_id: str, aweme_ids: list[str]) -> str:
        posts = {row["aweme_id"]: row for row in self.db.list_posts(profile_id, "all")}
        selected = []
        for aweme_id in dict.fromkeys(aweme_ids):
            post = posts.get(aweme_id)
            if not post or not post["metadata_error_code"]:
                raise ValueError(f"只能重试元数据失败作品：{aweme_id}")
            selected.append(aweme_id)
        return await self.create_metadata_refresh(profile_id, selected)

    def cancel(self, job_id: str) -> None:
        if not self.db.get_job(job_id):
            raise KeyError(job_id)
        self.db.set_cancel_requested(job_id)

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        result = []
        for row in self.db.list_jobs(limit):
            item = dict(row)
            current = json.loads(row["current_item"]) if row["current_item"] else None
            item["job_id"] = item.pop("id")
            item["current_item"] = current
            result.append(item)
        return result

    def delete_job(self, job_id: str) -> str:
        row = self.db.get_job(job_id)
        if not row:
            raise KeyError(job_id)
        if row["status"] in {"queued", "enumerating", "downloading"}:
            self.db.set_cancel_requested(job_id)
            return "cancellation_requested"
        self.db.delete_job(job_id)
        return "deleted"

    def status(self, job_id: str) -> JobStatus:
        row = self.db.get_job(job_id)
        if not row:
            raise KeyError(job_id)
        current = json.loads(row["current_item"]) if row["current_item"] else None
        items = [JobItem(**dict(item)) for item in self.db.list_job_items(job_id)]
        return JobStatus(job_id=row["id"], kind=row["kind"], profile_id=row["profile_id"], refresh_id=row["refresh_id"], status=row["status"], phase=row["phase"], discovered=row["discovered"], queued=row["queued"], completed=row["completed"], skipped=row["skipped"], failed=row["failed"], current_item=CurrentItem(**current) if current else None, items=items, error=row["error"], created_at=row["created_at"], updated_at=row["updated_at"])

    async def events(self, job_id: str):
        previous = None
        while True:
            status = self.status(job_id)
            serialized = status.model_dump_json()
            if serialized != previous:
                yield f"event: status\ndata: {serialized}\n\n"
                previous = serialized
            if status.status in {"completed", "completed_with_errors", "failed", "cancelled", "pending_confirmation"}:
                return
            await asyncio.sleep(1)

    async def profile_events(self, profile_id: str):
        previous = None
        while True:
            payload = {"profile": self.get_profile(profile_id), "posts": self.posts(profile_id, "all")}
            serialized = json.dumps(payload, ensure_ascii=False, default=str)
            if serialized != previous:
                yield f"event: profile\ndata: {serialized}\n\n"
                previous = serialized
            await asyncio.sleep(1)

    def files(self, job_id: str) -> list[dict[str, Any]]:
        row = self.db.get_job(job_id)
        if not row:
            raise KeyError(job_id)
        profile = self.db.profile_by_id(row["profile_id"]) if row["profile_id"] else None
        profile_dir = profile["media_dir"] if profile else "single"
        directory = self.settings.download_root / profile_dir
        result = []
        if not directory.is_dir():
            return result
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.name.endswith((".part", ".ytdl", ".nfo")) and path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                relative = path.relative_to(self.settings.download_root)
                file_id = str(relative)
                result.append({"file_id": file_id, "name": path.name, "size": path.stat().st_size, "download_url": f"/api/jobs/{job_id}/files/{file_id}"})
        return result

    def profile_file(self, profile_id: str, file_id: str) -> tuple[Path, str]:
        profile = self.db.profile_by_id(profile_id)
        if not profile:
            raise KeyError(profile_id)
        root = self.settings.download_root.resolve()
        base = (root / profile["media_dir"]).resolve()
        path = (root / file_id).resolve()
        if base not in path.parents or not path.is_file() or path.name.endswith((".part", ".ytdl")):
            raise FileNotFoundError(file_id)
        return path, path.name

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self._run(job_id)
            finally:
                self.queue.task_done()

    async def _run(self, job_id: str) -> None:
        row = self.db.get_job(job_id)
        if not row:
            return
        try:
            if row["kind"] == "refresh":
                await self._run_refresh(job_id, row)
            elif row["kind"] == "metadata":
                await self._run_metadata(job_id, row)
            else:
                await self._run_download(job_id, row)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = _safe_error(str(exc))
            self.db.update_job(job_id, status="failed", phase="error", error=message, current_item=None)
            if row["refresh_id"]:
                self.db.complete_refresh(row["refresh_id"], {}, status="failed", error=message)

    async def _run_refresh(self, job_id: str, job: Any) -> None:
        profile = self.db.profile_by_id(job["profile_id"])
        refresh_id = job["refresh_id"]
        self.db.update_job(job_id, status="enumerating", phase="enumerating")
        self.db.set_profile_refresh(job["profile_id"], "enumerating")
        self.db.update_refresh_progress(refresh_id, 0, "enumerating")
        posts: list[DouyinPost] = []
        try:
            async for post in self.profile.iter_posts(profile["profile_url"], max_items=job["max_items"], time_range=job["time_range"]):
                posts.append(post)
                if post.author_name and post.author_name != profile["display_name"]:
                    self.db.update_profile_display_name(job["profile_id"], post.author_name)
                    profile = self.db.profile_by_id(job["profile_id"]) or profile
                self.db.update_job(job_id, discovered=len(posts), current_item={"status": "enumerating", "aweme_id": post.aweme_id, "title": post.title})
                self.db.update_refresh_progress(refresh_id, len(posts), "enumerating")
                if self.db.cancel_requested(job_id):
                    self.db.complete_refresh(refresh_id, {"discovered": len(posts)}, status="cancelled")
                    self.db.update_job(job_id, status="cancelled", phase="cancelled", current_item=None)
                    return
            existing = {row["aweme_id"]: row for row in self.db.list_posts(job["profile_id"], "all")}
            discovered_ids = {post.aweme_id for post in posts}
            refresh_items: list[dict[str, Any]] = []
            counts = {"discovered": len(posts), "new": 0, "changed": 0, "missing": 0, "skipped": 0}
            for post in posts:
                old = existing.get(post.aweme_id)
                if post.aweme_type in IMAGE_TYPES:
                    change_type, reason = "image", "图集作品暂不支持视频下载"
                    counts["skipped"] += 1
                elif post.aweme_type not in VIDEO_TYPES and post.aweme_type is not None:
                    change_type, reason = "unknown", "未知作品类型，暂不下载"
                    counts["skipped"] += 1
                elif not old:
                    change_type, reason = "new", None
                    counts["new"] += 1
                elif (old["title"], old["upload_date"], old["aweme_type"]) != (post.title, post.upload_date, post.aweme_type):
                    change_type, reason = "metadata_changed", None
                    counts["changed"] += 1
                else:
                    change_type, reason = "unchanged", None
                refresh_items.append({"aweme_id": post.aweme_id, "title": post.title, "upload_date": post.upload_date, "aweme_type": post.aweme_type, "video_url": f"https://www.douyin.com/video/{post.aweme_id}", "change_type": change_type, "skip_reason": reason})
            # A bounded refresh intentionally does not observe older pages.
            # Only an all-time refresh has enough coverage to declare an
            # existing post missing from the remote profile.
            if job["time_range"] == "all":
                for aweme_id, old in existing.items():
                    if old["remote_state"] == "active" and aweme_id not in discovered_ids:
                        counts["missing"] += 1
                        refresh_items.append({"aweme_id": aweme_id, "title": old["title"], "upload_date": old["upload_date"], "aweme_type": old["aweme_type"], "video_url": old["video_url"], "change_type": "remote_missing", "skip_reason": "作品已不在当前主页"})
            self.db.add_refresh_items(refresh_id, refresh_items)
            current_profile = self.db.profile_by_id(job["profile_id"])
            if current_profile:
                write_profile_nfo(current_profile, self.settings.download_root / current_profile["media_dir"] / "tvshow.nfo")
            self.db.complete_refresh(refresh_id, counts, status="pending_confirmation")
            self.db.update_job(job_id, status="pending_confirmation", phase="confirmation", current_item=None)
        except Exception:
            raise

    def _store_metadata(self, profile_id: str, aweme_id: str, metadata: dict[str, Any] | None) -> None:
        # Keep the worker resilient if an extractor returns no info object.
        # Discovery metadata remains authoritative for fields yt-dlp could
        # not provide in this pass.
        if not isinstance(metadata, dict):
            metadata = {}
        post = self.db.get_post(profile_id, aweme_id)
        profile = self.db.profile_by_id(profile_id)
        if not post or not profile:
            raise ValueError("主页作品记录不存在")
        fields = {
            key: metadata.get(key)
            for key in (
                "description", "timestamp", "channel", "channel_id", "channel_url", "uploader", "uploader_id", "uploader_url",
                "duration", "view_count", "like_count", "comment_count", "repost_count", "save_count",
                "format_id", "width", "height", "fps", "vcodec", "acodec", "filesize",
                "container_ext", "track", "artists_json", "album", "availability",
            )
            if metadata.get(key) is not None
        }
        if metadata.get("title"):
            fields["title"] = metadata["title"]
        if metadata.get("upload_date"):
            fields["upload_date"] = metadata["upload_date"]
            fields["aired_date"] = metadata["upload_date"]
        fields["metadata_updated_at"] = utc_now()
        fields["metadata_error_code"] = None
        fields["metadata_error_message"] = None
        if metadata.get("channel") and metadata["channel"] != profile["display_name"]:
            self.db.update_profile_display_name(profile_id, str(metadata["channel"]))
            profile = self.db.profile_by_id(profile_id) or profile
            write_profile_nfo(profile, self.settings.download_root / profile["media_dir"] / "tvshow.nfo")
        self.db.update_post(profile_id, aweme_id, **fields)
        post = self.db.get_post(profile_id, aweme_id)
        assert post is not None
        profile_dir = self.settings.download_root / profile["media_dir"]
        season_dir = profile_dir / f"Season {int(post['season_number'] or 0)}"
        season_dir.mkdir(parents=True, exist_ok=True)
        write_season_nfo(profile, int(post["season_number"] or 0), season_dir / "season.nfo")
        thumb_file = post["thumbnail_file"]
        artwork_error = None
        thumbnail_urls = metadata.get("thumbnail_urls") or ([metadata["thumbnail_url"]] if metadata.get("thumbnail_url") else [])
        if thumbnail_urls:
            if thumb_file:
                destination = self.settings.download_root / thumb_file
            elif post["media_file"]:
                media_path = Path(post["media_file"])
                destination = self.settings.download_root / media_path.parent / f"{media_path.stem}-thumb"
            else:
                destination = season_dir / f"{aweme_id}-thumb"
            image, digest = download_image(thumbnail_urls, destination, {"User-Agent": self.settings.user_agent, "Referer": "https://www.douyin.com/"}, self.settings.request_timeout)
            if image:
                thumb_file = str(image.relative_to(self.settings.download_root))
                self.db.update_post(profile_id, aweme_id, thumbnail_file=thumb_file, thumbnail_source_hash=digest, artwork_error_code=None, artwork_error_message=None)
            else:
                artwork_error = digest
        elif not thumb_file:
            artwork_error = None
        if artwork_error:
            self.db.update_post(profile_id, aweme_id, artwork_error_code=artwork_error, artwork_error_message="无法下载视频封面")
        post = self.db.get_post(profile_id, aweme_id)
        assert post is not None
        nfo_file = post["nfo_file"]
        if post["media_file"]:
            if not nfo_file:
                nfo_file = str((self.settings.download_root / post["media_file"]).with_suffix(".nfo").relative_to(self.settings.download_root))
                self.db.update_post(profile_id, aweme_id, nfo_file=nfo_file)
                post = self.db.get_post(profile_id, aweme_id)
            if post:
                write_episode_nfo(profile, post, self.settings.download_root / nfo_file)
        self.db.update_profile_metadata(profile_id, metadata_updated_at=utc_now(), metadata_error_code=None, metadata_error_message=None)

    async def _run_download(self, job_id: str, job: Any) -> None:
        self.db.update_job(job_id, status="downloading", phase="download")
        for item in self.db.list_job_items(job_id):
            if item["status"] != "queued":
                continue
            if self.db.cancel_requested(job_id):
                self.db.update_job(job_id, status="cancelled", phase="cancelled", current_item=None)
                return
            profile_id = job["profile_id"]
            post = self.db.get_post(profile_id, item["aweme_id"]) if profile_id else None
            if not post and profile_id:
                self.db.update_job_item(job_id, item["aweme_id"], status="failed", error_code="not_found", error_message="主页作品记录不存在")
                continue
            if not post:
                post = {"video_url": item["video_url"], "title": item["title"]}
            # Profile posts come from sqlite3 with a Row factory, which
            # supports mapping access but not dict.get(). Legacy single-video
            # jobs use the fallback dict above, so select the value by branch.
            attempt_value = post["attempt_count"] if profile_id else item["attempt_count"]
            attempt = int(attempt_value or 0) + 1
            now = datetime.now(timezone.utc).isoformat()
            if profile_id:
                self.db.update_post(profile_id, item["aweme_id"], download_status="downloading", attempt_count=attempt, last_attempt_at=now)
            self.db.update_job_item(job_id, item["aweme_id"], status="downloading", attempt_count=attempt)
            self.db.update_job(job_id, current_item={"aweme_id": item["aweme_id"], "title": post["title"], "status": "downloading", "percent": 0})

            def progress(data: dict[str, Any]) -> None:
                percent = data.get("percent")
                if isinstance(percent, str):
                    try:
                        percent = float(percent.replace("%", "").strip())
                    except ValueError:
                        percent = None
                self.db.update_job_item(job_id, item["aweme_id"], status=data.get("status") or "downloading", percent=percent, speed=data.get("speed"), eta=data.get("eta"), file_name=Path(data["filename"]).name if data.get("filename") else None)
                self.db.update_job(job_id, current_item={"aweme_id": item["aweme_id"], "title": post["title"], "status": data.get("status"), "percent": percent, "speed": data.get("speed"), "eta": data.get("eta")})

            def message(value: str) -> None:
                safe = _safe_error(value)
                self.db.update_job_item(job_id, item["aweme_id"], error_code=_error_code(safe), error_message=safe)

            try:
                if profile_id:
                    profile = self.db.profile_by_id(profile_id)
                    if not profile:
                        raise RuntimeError("主页记录不存在")
                    season = int(post["season_number"] or 0)
                    episode = int(post["episode_number"] or 1)
                    output_dir = self.settings.download_root / profile["media_dir"] / f"Season {season}"
                    prefix = f"S{season:04d}E{episode:04d} - "
                else:
                    output_dir = single_media_dir(self.settings.download_root, item["aweme_id"])
                    prefix = ""
                path, metadata = await asyncio.to_thread(self.ytdlp.download_one, post["video_url"], output_dir, item["aweme_id"], prefix, progress, message)
                if not path:
                    raise RuntimeError("下载完成但未找到输出文件")
                if not isinstance(metadata, dict):
                    metadata = {"id": str(item["aweme_id"])}
                self.db.update_job_item(job_id, item["aweme_id"], status="downloaded", percent=100, file_name=path.name)
                if profile_id:
                    media_file = str(path.relative_to(self.settings.download_root))
                    self.db.update_post(profile_id, item["aweme_id"], download_status="downloaded", download_file=path.name, media_file=media_file, media_title_at_download=metadata.get("title") or post["title"], downloaded_at=datetime.now(timezone.utc).isoformat(), last_error_code=None, last_error_message=None)
                    self._store_metadata(profile_id, item["aweme_id"], metadata)
                else:
                    thumbnail_file = None
                    thumbnail_urls = metadata.get("thumbnail_urls") or ([metadata["thumbnail_url"]] if metadata.get("thumbnail_url") else [])
                    if thumbnail_urls:
                        image, _ = await asyncio.to_thread(
                            download_image,
                            thumbnail_urls,
                            path.with_name(f"{path.stem}-thumb"),
                            {"User-Agent": self.settings.user_agent, "Referer": "https://www.douyin.com/"},
                            self.settings.request_timeout,
                        )
                        if image:
                            thumbnail_file = str(image)
                    single_post = {
                        "title": metadata.get("title") or item["title"] or item["aweme_id"],
                        "description": metadata.get("description"),
                        "upload_date": metadata.get("upload_date"),
                        "duration": metadata.get("duration"),
                        "aweme_id": item["aweme_id"],
                        "thumbnail_file": thumbnail_file,
                        "video_url": post["video_url"],
                    }
                    write_movie_nfo(single_post, path.with_name("movie.nfo"))
            except Exception as exc:
                safe = _safe_error(str(exc))
                code = _error_code(safe)
                self.db.update_job_item(job_id, item["aweme_id"], status="failed", error_code=code, error_message=safe)
                if profile_id:
                    self.db.update_post(profile_id, item["aweme_id"], download_status="failed", last_error_code=code, last_error_message=safe)
        final = self.db.get_job(job_id)
        if final and final["cancel_requested"]:
            self.db.update_job(job_id, status="cancelled", phase="cancelled", current_item=None)
        else:
            self.db.update_job(job_id, status="completed_with_errors" if self.db.get_job(job_id)["failed"] else "completed", phase="complete", current_item=None)

    async def _run_metadata(self, job_id: str, job: Any) -> None:
        self.db.update_job(job_id, status="processing", phase="metadata")
        for item in self.db.list_job_items(job_id):
            if item["status"] != "queued":
                continue
            if self.db.cancel_requested(job_id):
                self.db.update_job(job_id, status="cancelled", phase="cancelled", current_item=None)
                return
            profile_id = job["profile_id"]
            post = self.db.get_post(profile_id, item["aweme_id"])
            if not post:
                self.db.update_job_item(job_id, item["aweme_id"], status="failed", error_code="not_found", error_message="主页作品记录不存在")
                continue
            self.db.update_job_item(job_id, item["aweme_id"], status="processing")
            self.db.update_job(job_id, current_item={"aweme_id": item["aweme_id"], "title": post["title"], "status": "processing", "percent": 0})

            def message(value: str) -> None:
                safe = _safe_error(value)
                self.db.update_job_item(job_id, item["aweme_id"], error_code=_error_code(safe), error_message=safe)

            try:
                metadata = await asyncio.to_thread(self.ytdlp.extract_metadata, post["video_url"], message)
                self._store_metadata(profile_id, item["aweme_id"], metadata)
                self.db.update_job_item(job_id, item["aweme_id"], status="updated", percent=100)
            except Exception as exc:
                safe = _safe_error(str(exc))
                code = _error_code(safe)
                self.db.update_job_item(job_id, item["aweme_id"], status="failed", error_code=code, error_message=safe)
                self.db.update_post(profile_id, item["aweme_id"], metadata_error_code=code, metadata_error_message=safe)
        final = self.db.get_job(job_id)
        if final and final["cancel_requested"]:
            self.db.update_job(job_id, status="cancelled", phase="cancelled", current_item=None)
        else:
            self.db.update_job(job_id, status="completed_with_errors" if self.db.get_job(job_id)["failed"] else "completed", phase="complete", current_item=None)

    async def _single_id(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        if not ProfileService._validate_host(parsed.hostname):
            raise ValueError("Only douyin.com URLs are supported")
        query = parse_qs(parsed.query)
        for key in ("modal_id", "vid"):
            value = query.get(key, [None])[0]
            if value and value.isdigit():
                return value
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"video", "note"} and parts[1].isdigit():
            return parts[1]
        if parsed.hostname == "v.douyin.com":
            async with httpx.AsyncClient(follow_redirects=True, timeout=self.settings.request_timeout, proxy=self.settings.proxy, headers={"User-Agent": self.settings.user_agent}) as client:
                response = await client.get(source_url)
                response.raise_for_status()
                final = urlparse(str(response.url))
                query = parse_qs(final.query)
                for key in ("modal_id", "vid"):
                    value = query.get(key, [None])[0]
                    if value and value.isdigit():
                        return value
                parts = [part for part in final.path.split("/") if part]
                if len(parts) >= 2 and parts[0] in {"video", "note"} and parts[1].isdigit():
                    return parts[1]
        raise ValueError("Unable to resolve a Douyin video ID")
