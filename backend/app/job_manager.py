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
from .db import JobDB
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
            return self.profile_summary(existing)
        display_name = await self.profile.fetch_profile_name(sec_user_id)
        return self.profile_summary(self.db.create_profile(sec_user_id, source_url, display_name))

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
        return dict(self.db.apply_refresh(refresh_id, selected_ids))

    def posts(self, profile_id: str, status_filter: str = "all") -> list[dict[str, Any]]:
        if not self.db.profile_by_id(profile_id):
            raise KeyError(profile_id)
        result = []
        for row in self.db.list_posts(profile_id, status_filter):
            item = dict(row)
            item["file_exists"] = bool(row["download_file"] and (self.settings.download_root / profile_id / row["download_file"]).is_file())
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
            if post["download_status"] == "downloaded":
                item.update(status="already_downloaded", file_name=post["download_file"], skip_reason_code="already_downloaded", skip_reason_message="该作品已下载")
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
        profile_dir = row["profile_id"] or "single"
        directory = self.settings.download_root / profile_dir
        result = []
        if not directory.is_dir():
            return result
        for path in sorted(directory.iterdir()):
            if path.is_file() and not path.name.endswith((".part", ".ytdl")):
                result.append({"file_id": f"{profile_dir}/{path.name}", "name": path.name, "size": path.stat().st_size, "download_url": f"/api/jobs/{job_id}/files/{profile_dir}/{path.name}"})
        return result

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
            for aweme_id, old in existing.items():
                if old["remote_state"] == "active" and aweme_id not in discovered_ids:
                    counts["missing"] += 1
                    refresh_items.append({"aweme_id": aweme_id, "title": old["title"], "upload_date": old["upload_date"], "aweme_type": old["aweme_type"], "video_url": old["video_url"], "change_type": "remote_missing", "skip_reason": "作品已不在当前主页"})
            self.db.add_refresh_items(refresh_id, refresh_items)
            self.db.complete_refresh(refresh_id, counts, status="pending_confirmation")
            self.db.update_job(job_id, status="pending_confirmation", phase="confirmation", current_item=None)
        except Exception:
            raise

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
                output_dir = self.settings.download_root / (profile_id or "single")
                path = await asyncio.to_thread(self.ytdlp.download_one, post["video_url"], output_dir, item["aweme_id"], post["title"], progress, message)
                if not path:
                    raise RuntimeError("下载完成但未找到输出文件")
                self.db.update_job_item(job_id, item["aweme_id"], status="downloaded", percent=100, file_name=path.name)
                if profile_id:
                    self.db.update_post(profile_id, item["aweme_id"], download_status="downloaded", download_file=path.name, downloaded_at=datetime.now(timezone.utc).isoformat(), last_error_code=None, last_error_message=None)
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
