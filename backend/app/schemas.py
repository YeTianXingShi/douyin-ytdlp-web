from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


JobMode = Literal["single", "user_posts"]
PostFilter = Literal["all", "not_downloaded", "downloaded", "failed", "skipped", "remote_missing"]
RefreshTimeRange = Literal["all", "week", "month", "quarter", "half_year", "year"]


class ProfileCreate(BaseModel):
    source_url: str = Field(min_length=1, max_length=4096)

    @field_validator("source_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source_url cannot be empty")
        return value


class JobCreate(BaseModel):
    source_url: str = Field(min_length=1, max_length=4096)
    mode: JobMode
    max_items: int = Field(default=0, ge=0, le=10000)


class ProfileSummary(BaseModel):
    id: str
    sec_user_id: str
    profile_url: str
    display_name: str | None = None
    last_refresh_at: datetime | None = None
    last_refresh_status: str | None = None
    last_refresh_error: str | None = None
    post_count: int = 0
    downloaded_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    pending_refresh_id: str | None = None


class ProfileRefreshCreate(BaseModel):
    max_items: int = Field(default=0, ge=0, le=10000)
    time_range: RefreshTimeRange = "all"


class RefreshSummary(BaseModel):
    id: str
    profile_id: str
    job_id: str | None = None
    status: str
    time_range: RefreshTimeRange = "all"
    discovered_count: int = 0
    new_count: int = 0
    changed_count: int = 0
    missing_count: int = 0
    skipped_count: int = 0
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class RefreshItem(BaseModel):
    refresh_id: str
    aweme_id: str
    title: str | None = None
    upload_date: str | None = None
    aweme_type: int | None = None
    video_url: str
    change_type: str
    is_selected: bool = False
    skip_reason: str | None = None


class RefreshApply(BaseModel):
    selected_aweme_ids: list[str] = Field(default_factory=list)


class DownloadCreate(BaseModel):
    aweme_ids: list[str] = Field(min_length=1, max_length=10000)


class RetryCreate(BaseModel):
    aweme_ids: list[str] = Field(min_length=1, max_length=10000)


class JobCreated(BaseModel):
    job_id: str
    status: str


class CurrentItem(BaseModel):
    aweme_id: str | None = None
    title: str | None = None
    status: str | None = None
    percent: float | None = None
    speed: str | None = None
    eta: str | None = None
    error: str | None = None


class JobSummary(BaseModel):
    job_id: str
    kind: str
    profile_id: str | None = None
    refresh_id: str | None = None
    display_name: str | None = None
    sec_user_id: str | None = None
    status: str
    phase: str
    discovered: int = 0
    queued: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0
    current_item: CurrentItem | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class JobItem(BaseModel):
    aweme_id: str
    title: str | None = None
    status: str
    percent: float | None = None
    speed: str | None = None
    eta: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    skip_reason_code: str | None = None
    skip_reason_message: str | None = None
    attempt_count: int = 0
    file_name: str | None = None


class JobStatus(BaseModel):
    job_id: str
    kind: str
    profile_id: str | None = None
    refresh_id: str | None = None
    status: str
    phase: str
    discovered: int = 0
    queued: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0
    current_item: CurrentItem | None = None
    items: list[JobItem] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ProfilePost(BaseModel):
    profile_id: str
    aweme_id: str
    title: str | None = None
    upload_date: str | None = None
    aweme_type: int | None = None
    video_url: str
    remote_state: str
    download_status: str
    download_file: str | None = None
    downloaded_at: datetime | None = None
    attempt_count: int = 0
    last_attempt_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    skip_reason_code: str | None = None
    skip_reason_message: str | None = None
    file_exists: bool = False
    updated_at: datetime


class JobFile(BaseModel):
    file_id: str
    name: str
    size: int
    download_url: str
