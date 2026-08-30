from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


POST_METADATA_FIELDS = {
    "description", "timestamp", "channel", "channel_id", "channel_url", "uploader", "uploader_id", "uploader_url",
    "view_count", "like_count", "comment_count", "repost_count", "save_count",
    "stats_updated_at", "duration", "thumbnail_file", "thumbnail_source_hash",
    "format_id", "width", "height", "fps", "vcodec", "acodec", "filesize",
    "container_ext", "track", "artists_json", "album", "availability",
    "media_file", "nfo_file", "media_title_at_download", "metadata_updated_at",
    "metadata_error_code", "metadata_error_message", "artwork_error_code",
    "artwork_error_message", "season_number", "episode_number", "aired_date",
}


class JobDB:
    """SQLite persistence for profiles, Jellyfin media metadata and jobs."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            existing = self._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='profile_posts'").fetchone()
            if existing:
                columns = {row[1] for row in self._conn.execute("PRAGMA table_info(profile_posts)")}
                if "season_number" not in columns or "media_file" not in columns:
                    raise RuntimeError(f"数据库结构不兼容：{self.path}。请备份并删除旧 state 后重新启动")
            jobs_existing = self._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
            if jobs_existing:
                job_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(jobs)")}
                if "kind" not in job_columns or "cancel_requested" not in job_columns:
                    raise RuntimeError(f"数据库结构不兼容：{self.path}。请备份并删除旧 state 后重新启动")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    sec_user_id TEXT NOT NULL UNIQUE,
                    profile_url TEXT NOT NULL,
                    display_name TEXT,
                    media_dir TEXT NOT NULL,
                    poster_file TEXT,
                    backdrop_file TEXT,
                    metadata_updated_at TEXT,
                    metadata_error_code TEXT,
                    metadata_error_message TEXT,
                    last_refresh_at TEXT,
                    last_refresh_status TEXT,
                    last_refresh_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_refreshes (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    job_id TEXT,
                    status TEXT NOT NULL,
                    discovered_count INTEGER NOT NULL DEFAULT 0,
                    new_count INTEGER NOT NULL DEFAULT 0,
                    changed_count INTEGER NOT NULL DEFAULT 0,
                    missing_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    time_range TEXT NOT NULL DEFAULT 'all',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS profile_refresh_items (
                    refresh_id TEXT NOT NULL REFERENCES profile_refreshes(id) ON DELETE CASCADE,
                    aweme_id TEXT NOT NULL,
                    title TEXT,
                    upload_date TEXT,
                    aweme_type INTEGER,
                    video_url TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    is_selected INTEGER NOT NULL DEFAULT 0,
                    skip_reason TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(refresh_id, aweme_id)
                );
                CREATE TABLE IF NOT EXISTS profile_posts (
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    aweme_id TEXT NOT NULL,
                    title TEXT,
                    description TEXT,
                    upload_date TEXT,
                    timestamp INTEGER,
                    aweme_type INTEGER,
                    video_url TEXT NOT NULL,
                    channel TEXT,
                    channel_id TEXT,
                    channel_url TEXT,
                    uploader TEXT,
                    uploader_id TEXT,
                    uploader_url TEXT,
                    remote_state TEXT NOT NULL DEFAULT 'active',
                    download_status TEXT NOT NULL DEFAULT 'not_downloaded',
                    download_file TEXT,
                    media_file TEXT,
                    nfo_file TEXT,
                    thumbnail_file TEXT,
                    downloaded_at TEXT,
                    media_title_at_download TEXT,
                    season_number INTEGER,
                    episode_number INTEGER,
                    aired_date TEXT,
                    duration REAL,
                    view_count INTEGER,
                    like_count INTEGER,
                    comment_count INTEGER,
                    repost_count INTEGER,
                    save_count INTEGER,
                    stats_updated_at TEXT,
                    thumbnail_source_hash TEXT,
                    format_id TEXT,
                    width INTEGER,
                    height INTEGER,
                    fps REAL,
                    vcodec TEXT,
                    acodec TEXT,
                    filesize INTEGER,
                    container_ext TEXT,
                    track TEXT,
                    artists_json TEXT,
                    album TEXT,
                    availability TEXT,
                    metadata_updated_at TEXT,
                    metadata_error_code TEXT,
                    metadata_error_message TEXT,
                    artwork_error_code TEXT,
                    artwork_error_message TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT,
                    last_error_code TEXT,
                    last_error_message TEXT,
                    skip_reason_code TEXT,
                    skip_reason_message TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(profile_id, aweme_id)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    profile_id TEXT REFERENCES profiles(id) ON DELETE SET NULL,
                    refresh_id TEXT REFERENCES profile_refreshes(id) ON DELETE SET NULL,
                    max_items INTEGER NOT NULL DEFAULT 0,
                    time_range TEXT NOT NULL DEFAULT 'all',
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    discovered INTEGER NOT NULL DEFAULT 0,
                    queued INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    current_item TEXT,
                    error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_items (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    aweme_id TEXT NOT NULL,
                    video_url TEXT,
                    title TEXT,
                    status TEXT NOT NULL,
                    percent REAL,
                    speed TEXT,
                    eta TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    skip_reason_code TEXT,
                    skip_reason_message TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    file_name TEXT,
                    PRIMARY KEY(job_id, aweme_id)
                );
                CREATE INDEX IF NOT EXISTS idx_posts_profile_status ON profile_posts(profile_id, download_status);
                CREATE INDEX IF NOT EXISTS idx_posts_metadata ON profile_posts(profile_id, metadata_updated_at);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                """
            )
            self._conn.commit()

    def _execute(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, args)
            self._conn.commit()
            return cursor

    def _many(self, sql: str, rows: Iterable[tuple[Any, ...]]) -> None:
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    def profile_by_id(self, profile_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()

    def profile_by_sec_id(self, sec_user_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM profiles WHERE sec_user_id = ?", (sec_user_id,)).fetchone()

    def list_profiles(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT * FROM profiles ORDER BY updated_at DESC").fetchall()

    def create_profile(self, sec_user_id: str, profile_url: str, display_name: str | None = None) -> sqlite3.Row:
        profile_id = str(uuid.uuid4())
        now = utc_now()
        media_dir = f"profiles/{sec_user_id}"
        self._execute("INSERT INTO profiles (id, sec_user_id, profile_url, display_name, media_dir, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (profile_id, sec_user_id, profile_url, display_name, media_dir, now, now))
        return self.profile_by_id(profile_id)

    def update_profile_display_name(self, profile_id: str, display_name: str) -> None:
        self._execute("UPDATE profiles SET display_name = ?, updated_at = ? WHERE id = ?", (display_name, utc_now(), profile_id))

    def update_profile_metadata(self, profile_id: str, **fields: Any) -> None:
        allowed = {k: v for k, v in fields.items() if k in {"poster_file", "backdrop_file", "metadata_updated_at", "metadata_error_code", "metadata_error_message"}}
        if allowed:
            assignments = ", ".join(f"{key} = ?" for key in allowed)
            self._execute(f"UPDATE profiles SET {assignments}, updated_at = ? WHERE id = ?", (*allowed.values(), utc_now(), profile_id))

    def delete_profile(self, profile_id: str) -> bool:
        cursor = self._execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        return cursor.rowcount > 0

    def set_profile_refresh(self, profile_id: str, status: str, error: str | None = None) -> None:
        self._execute("UPDATE profiles SET last_refresh_status = ?, last_refresh_error = ?, last_refresh_at = CASE WHEN ? IN ('pending_confirmation', 'applied', 'failed', 'cancelled') THEN ? ELSE last_refresh_at END, updated_at = ? WHERE id = ?", (status, error, status, utc_now(), utc_now(), profile_id))

    def profile_stats(self, profile_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT download_status, COUNT(*) AS count FROM profile_posts WHERE profile_id = ? GROUP BY download_status", (profile_id,)).fetchall()
        counts = {str(row["download_status"]): int(row["count"]) for row in rows}
        return {"post_count": sum(counts.values()), "downloaded_count": counts.get("downloaded", 0), "failed_count": counts.get("failed", 0), "skipped_count": counts.get("skipped", 0)}

    def create_refresh(self, profile_id: str, job_id: str, time_range: str = "all") -> str:
        refresh_id = str(uuid.uuid4())
        now = utc_now()
        self._execute("INSERT INTO profile_refreshes (id, profile_id, job_id, status, time_range, created_at) VALUES (?, ?, ?, 'queued', ?, ?)", (refresh_id, profile_id, job_id, time_range, now))
        self._execute("UPDATE jobs SET refresh_id = ? WHERE id = ?", (refresh_id, job_id))
        self.set_profile_refresh(profile_id, "queued")
        return refresh_id

    def active_refresh(self, profile_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT r.* FROM profile_refreshes r JOIN jobs j ON j.id = r.job_id WHERE r.profile_id = ? AND r.status IN ('queued', 'enumerating') AND j.status IN ('queued', 'enumerating') ORDER BY r.created_at DESC LIMIT 1", (profile_id,)).fetchone()

    def pending_refresh(self, profile_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM profile_refreshes WHERE profile_id = ? AND status = 'pending_confirmation' ORDER BY created_at DESC LIMIT 1", (profile_id,)).fetchone()

    def get_refresh(self, refresh_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM profile_refreshes WHERE id = ?", (refresh_id,)).fetchone()

    def list_refresh_items(self, refresh_id: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT * FROM profile_refresh_items WHERE refresh_id = ? ORDER BY created_at, aweme_id", (refresh_id,)).fetchall()

    def add_refresh_items(self, refresh_id: str, items: list[dict[str, Any]]) -> None:
        self._many("INSERT OR REPLACE INTO profile_refresh_items (refresh_id, aweme_id, title, upload_date, aweme_type, video_url, change_type, is_selected, skip_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)", [(refresh_id, item["aweme_id"], item.get("title"), item.get("upload_date"), item.get("aweme_type"), item["video_url"], item["change_type"], item.get("skip_reason"), utc_now()) for item in items])

    def complete_refresh(self, refresh_id: str, counts: dict[str, int], status: str = "pending_confirmation", error: str | None = None) -> None:
        refresh = self.get_refresh(refresh_id)
        if not refresh:
            raise KeyError(refresh_id)
        completed = utc_now() if status in {"pending_confirmation", "failed", "cancelled", "applied"} else None
        self._execute("UPDATE profile_refreshes SET status = ?, discovered_count = ?, new_count = ?, changed_count = ?, missing_count = ?, skipped_count = ?, error = ?, completed_at = ? WHERE id = ?", (status, counts.get("discovered", 0), counts.get("new", 0), counts.get("changed", 0), counts.get("missing", 0), counts.get("skipped", 0), error, completed, refresh_id))
        self.set_profile_refresh(refresh["profile_id"], status, error)

    def update_refresh_progress(self, refresh_id: str, discovered_count: int, status: str = "enumerating") -> None:
        self._execute("UPDATE profile_refreshes SET status = ?, discovered_count = ? WHERE id = ?", (status, discovered_count, refresh_id))

    def _next_episode_locked(self, profile_id: str, season_number: int) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(episode_number), 0) AS max_episode FROM profile_posts WHERE profile_id = ? AND season_number = ?", (profile_id, season_number)).fetchone()
        return int(row["max_episode"] or 0) + 1

    def apply_refresh(self, refresh_id: str, selected_ids: list[str]) -> sqlite3.Row:
        refresh = self.get_refresh(refresh_id)
        if not refresh:
            raise KeyError(refresh_id)
        selected = set(selected_ids)
        with self._lock:
            items = self._conn.execute("SELECT * FROM profile_refresh_items WHERE refresh_id = ?", (refresh_id,)).fetchall()
            discovered_ids = {row["aweme_id"] for row in items}
            now = utc_now()
            if refresh["time_range"] == "all":
                if discovered_ids:
                    placeholders = ",".join("?" * len(discovered_ids))
                    self._conn.execute(f"UPDATE profile_posts SET remote_state = 'remote_missing', updated_at = ? WHERE profile_id = ? AND aweme_id NOT IN ({placeholders})", (now, refresh["profile_id"], *discovered_ids))
                else:
                    self._conn.execute("UPDATE profile_posts SET remote_state = 'remote_missing', updated_at = ? WHERE profile_id = ?", (now, refresh["profile_id"]))
            for row in items:
                if row["aweme_id"] not in selected:
                    continue
                old = self._conn.execute("SELECT * FROM profile_posts WHERE profile_id = ? AND aweme_id = ?", (refresh["profile_id"], row["aweme_id"])).fetchone()
                is_video = row["aweme_type"] in {None, 0, 4}
                status = "not_downloaded" if is_video else "skipped"
                skip_code = None if is_video else ("image_post" if row["aweme_type"] in {2, 68} else "unknown_type")
                skip_message = None if is_video else ("图集作品暂不支持视频下载" if skip_code == "image_post" else "未知作品类型，暂不下载")
                season = int(row["upload_date"][:4]) if row["upload_date"] and str(row["upload_date"])[:4].isdigit() else 0
                episode = old["episode_number"] if old and old["episode_number"] else (self._next_episode_locked(refresh["profile_id"], season) if is_video else None)
                if old and old["download_status"] == "downloaded":
                    status = "downloaded"
                self._conn.execute("""INSERT INTO profile_posts (profile_id, aweme_id, title, upload_date, aweme_type, video_url, remote_state, download_status, skip_reason_code, skip_reason_message, season_number, episode_number, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id, aweme_id) DO UPDATE SET title=excluded.title, upload_date=excluded.upload_date, aweme_type=excluded.aweme_type, video_url=excluded.video_url, remote_state='active', download_status=CASE WHEN profile_posts.download_status='downloaded' THEN 'downloaded' ELSE excluded.download_status END, skip_reason_code=excluded.skip_reason_code, skip_reason_message=excluded.skip_reason_message, season_number=COALESCE(profile_posts.season_number, excluded.season_number), episode_number=COALESCE(profile_posts.episode_number, excluded.episode_number), updated_at=excluded.updated_at""", (refresh["profile_id"], row["aweme_id"], row["title"], row["upload_date"], row["aweme_type"], row["video_url"], status, skip_code, skip_message, season, episode, now))
            if selected:
                placeholders = ",".join("?" * len(selected))
                self._conn.execute(f"UPDATE profile_refresh_items SET is_selected = 1 WHERE refresh_id = ? AND aweme_id IN ({placeholders})", (refresh_id, *selected))
            self._conn.execute("UPDATE profile_refreshes SET status = 'applied', completed_at = ? WHERE id = ?", (now, refresh_id))
            self._conn.execute("UPDATE profiles SET last_refresh_status = 'applied', last_refresh_error = NULL, last_refresh_at = ?, updated_at = ? WHERE id = ?", (now, now, refresh["profile_id"]))
            self._conn.commit()
        return self.get_refresh(refresh_id)

    def list_posts(self, profile_id: str, status_filter: str = "all") -> list[sqlite3.Row]:
        sql = "SELECT * FROM profile_posts WHERE profile_id = ?"
        args: list[Any] = [profile_id]
        if status_filter == "remote_missing":
            sql += " AND remote_state = 'remote_missing'"
        elif status_filter == "not_downloaded":
            sql += " AND download_status = 'not_downloaded' AND remote_state = 'active'"
        elif status_filter in {"downloaded", "failed", "skipped"}:
            sql += " AND download_status = ?"
            args.append(status_filter)
        sql += " ORDER BY COALESCE(upload_date, '') DESC, aweme_id DESC"
        with self._lock:
            return self._conn.execute(sql, tuple(args)).fetchall()

    def get_post(self, profile_id: str, aweme_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM profile_posts WHERE profile_id = ? AND aweme_id = ?", (profile_id, aweme_id)).fetchone()

    def create_job(self, kind: str, profile_id: str | None = None, refresh_id: str | None = None, max_items: int = 0, time_range: str = "all") -> str:
        job_id = str(uuid.uuid4())
        now = utc_now()
        self._execute("INSERT INTO jobs (id, kind, profile_id, refresh_id, max_items, time_range, status, phase, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', 'queued', ?, ?)", (job_id, kind, profile_id, refresh_id, max_items, time_range, now, now))
        return job_id

    def add_job_items(self, job_id: str, items: list[dict[str, Any]]) -> None:
        self._many("INSERT OR REPLACE INTO job_items (job_id, aweme_id, video_url, title, status, error_code, error_message, skip_reason_code, skip_reason_message, attempt_count, file_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [(job_id, item["aweme_id"], item.get("video_url"), item.get("title"), item["status"], item.get("error_code"), item.get("error_message"), item.get("skip_reason_code"), item.get("skip_reason_message"), item.get("attempt_count", 0), item.get("file_name")) for item in items])
        self.update_job_counts(job_id)

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def list_jobs(self, limit: int = 100) -> list[sqlite3.Row]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            return self._conn.execute("SELECT j.*, p.display_name, p.sec_user_id FROM jobs j LEFT JOIN profiles p ON p.id = j.profile_id ORDER BY j.updated_at DESC LIMIT ?", (limit,)).fetchall()

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row["status"] in {"queued", "enumerating", "downloading", "processing"}:
                return False
            self._conn.execute("DELETE FROM profile_refreshes WHERE job_id = ?", (job_id,))
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()
            return True

    def list_job_items(self, job_id: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT * FROM job_items WHERE job_id = ? ORDER BY rowid", (job_id,)).fetchall()

    def update_job_counts(self, job_id: str, **overrides: int) -> None:
        if overrides:
            assignments = ", ".join(f"{key} = ?" for key in overrides)
            self._execute(f"UPDATE jobs SET {assignments}, updated_at = ? WHERE id = ?", (*overrides.values(), utc_now(), job_id))
            return
        with self._lock:
            rows = self._conn.execute("SELECT status, COUNT(*) AS n FROM job_items WHERE job_id = ? GROUP BY status", (job_id,)).fetchall()
        counts = {str(item["status"]): int(item["n"]) for item in rows}
        self._execute("UPDATE jobs SET discovered = ?, queued = ?, completed = ?, skipped = ?, failed = ?, updated_at = ? WHERE id = ?", (sum(counts.values()), counts.get("queued", 0) + counts.get("downloading", 0) + counts.get("processing", 0), counts.get("downloaded", 0) + counts.get("updated", 0), counts.get("skipped", 0) + counts.get("already_downloaded", 0), counts.get("failed", 0), utc_now(), job_id))

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {key: value for key, value in fields.items() if key in {"status", "phase", "error", "current_item", "discovered", "queued", "completed", "skipped", "failed"}}
        if "current_item" in allowed and isinstance(allowed["current_item"], dict):
            allowed["current_item"] = json.dumps(allowed["current_item"], ensure_ascii=False)
        if allowed:
            assignments = ", ".join(f"{key} = ?" for key in allowed)
            self._execute(f"UPDATE jobs SET {assignments}, updated_at = ? WHERE id = ?", (*allowed.values(), utc_now(), job_id))

    def update_job_item(self, job_id: str, aweme_id: str, **fields: Any) -> None:
        allowed = {key: value for key, value in fields.items() if key in {"status", "percent", "speed", "eta", "error_code", "error_message", "skip_reason_code", "skip_reason_message", "attempt_count", "file_name", "title", "video_url"}}
        if allowed:
            assignments = ", ".join(f"{key} = ?" for key in allowed)
            self._execute(f"UPDATE job_items SET {assignments} WHERE job_id = ? AND aweme_id = ?", (*allowed.values(), job_id, aweme_id))
            self.update_job_counts(job_id)

    def update_post(self, profile_id: str, aweme_id: str, **fields: Any) -> None:
        allowed = {key: value for key, value in fields.items() if key in POST_METADATA_FIELDS or key in {"download_status", "download_file", "downloaded_at", "attempt_count", "last_attempt_at", "last_error_code", "last_error_message", "skip_reason_code", "skip_reason_message", "remote_state", "title", "upload_date", "aweme_type", "video_url"}}
        if allowed:
            assignments = ", ".join(f"{key} = ?" for key in allowed)
            self._execute(f"UPDATE profile_posts SET {assignments}, updated_at = ? WHERE profile_id = ? AND aweme_id = ?", (*allowed.values(), utc_now(), profile_id, aweme_id))

    def set_cancel_requested(self, job_id: str) -> None:
        self._execute("UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?", (utc_now(), job_id))

    def cancel_requested(self, job_id: str) -> bool:
        row = self.get_job(job_id)
        return bool(row and row["cancel_requested"])

    def recover_running(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT id, profile_id, created_at FROM jobs WHERE status IN ('queued', 'enumerating', 'downloading', 'processing') ORDER BY created_at").fetchall()
            keep_profiles: set[str] = set()
            keep_ids: list[str] = []
            for row in rows:
                profile_id = row["profile_id"]
                if profile_id and profile_id in keep_profiles:
                    self._conn.execute("UPDATE jobs SET status = 'cancelled', phase = 'cancelled', error = '同一主页已有运行任务，重复任务已取消', updated_at = ? WHERE id = ?", (utc_now(), row["id"]))
                else:
                    if profile_id:
                        keep_profiles.add(profile_id)
                    keep_ids.append(row["id"])
            self._conn.execute("UPDATE jobs SET status = 'queued', phase = 'queued', current_item = NULL, updated_at = ? WHERE status IN ('enumerating', 'downloading', 'processing')", (utc_now(),))
            self._conn.execute("UPDATE job_items SET status = 'queued', percent = NULL, speed = NULL, eta = NULL WHERE status IN ('downloading', 'processing')")
            self._conn.commit()
            return keep_ids
