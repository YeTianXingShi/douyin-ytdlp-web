from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .job_manager import JobManager
from .schemas import (
    DownloadCreate,
    JobCreate,
    JobCreated,
    JobFile,
    JobSummary,
    JobStatus,
    ProfileCreate,
    ProfilePost,
    ProfileRefreshCreate,
    ProfileSummary,
    RefreshApply,
    RefreshItem,
    RefreshSummary,
    RetryCreate,
)
from .security import require_admin


app = FastAPI(title="Douyin yt-dlp Web Downloader", version=settings.app_version)
manager = JobManager(settings)


@app.on_event("startup")
async def startup() -> None:
    await manager.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await manager.stop()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}


@app.post("/api/jobs", response_model=JobCreated, dependencies=[Depends(require_admin)])
async def create_legacy_job(payload: JobCreate) -> dict:
    try:
        job_id = await manager.create_legacy_job(payload.source_url, payload.mode, payload.max_items)
        return {"job_id": job_id, "status": "queued"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/profiles", response_model=ProfileSummary, dependencies=[Depends(require_admin)])
async def create_profile(payload: ProfileCreate) -> dict:
    try:
        return await manager.add_profile(payload.source_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/profiles", response_model=list[ProfileSummary], dependencies=[Depends(require_admin)])
async def list_profiles() -> list[dict]:
    return manager.list_profiles()


@app.get("/api/profiles/{profile_id}", response_model=ProfileSummary, dependencies=[Depends(require_admin)])
async def get_profile(profile_id: str) -> dict:
    try:
        return manager.get_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc


@app.delete("/api/profiles/{profile_id}", dependencies=[Depends(require_admin)])
async def delete_profile(profile_id: str) -> dict[str, str]:
    try:
        manager.delete_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc
    return {"profile_id": profile_id, "status": "deleted"}


@app.post("/api/profiles/{profile_id}/refresh", response_model=RefreshSummary, dependencies=[Depends(require_admin)])
async def refresh_profile(profile_id: str, payload: ProfileRefreshCreate) -> dict:
    try:
        refresh_id = await manager.refresh_profile(profile_id, payload.max_items)
        summary = manager.refresh_summary(refresh_id)
        return summary
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc


@app.get("/api/profiles/{profile_id}/refreshes/{refresh_id}", response_model=RefreshSummary, dependencies=[Depends(require_admin)])
async def get_refresh(profile_id: str, refresh_id: str) -> dict:
    try:
        summary = manager.refresh_summary(refresh_id)
        if summary["profile_id"] != profile_id:
            raise KeyError(refresh_id)
        return summary
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Refresh not found") from exc


@app.get("/api/profiles/{profile_id}/refreshes/{refresh_id}/items", response_model=list[RefreshItem], dependencies=[Depends(require_admin)])
async def get_refresh_items(profile_id: str, refresh_id: str) -> list[dict]:
    try:
        summary = manager.refresh_summary(refresh_id)
        if summary["profile_id"] != profile_id:
            raise KeyError(refresh_id)
        return manager.refresh_items(refresh_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Refresh not found") from exc


@app.post("/api/profiles/{profile_id}/refreshes/{refresh_id}/apply", response_model=RefreshSummary, dependencies=[Depends(require_admin)])
async def apply_refresh(profile_id: str, refresh_id: str, payload: RefreshApply) -> dict:
    try:
        return manager.apply_refresh(profile_id, refresh_id, payload.selected_aweme_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Refresh not found") from exc


@app.get("/api/profiles/{profile_id}/posts", response_model=list[ProfilePost], dependencies=[Depends(require_admin)])
async def list_posts(profile_id: str, status: str = Query("all")) -> list[dict]:
    try:
        return manager.posts(profile_id, status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc


@app.post("/api/profiles/{profile_id}/downloads", response_model=JobCreated, dependencies=[Depends(require_admin)])
async def download_posts(profile_id: str, payload: DownloadCreate) -> dict:
    try:
        job_id = await manager.create_download(profile_id, payload.aweme_ids)
        return {"job_id": job_id, "status": "queued"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/profiles/{profile_id}/posts/retry", response_model=JobCreated, dependencies=[Depends(require_admin)])
async def retry_posts(profile_id: str, payload: RetryCreate) -> dict:
    try:
        job_id = await manager.retry_posts(profile_id, payload.aweme_ids)
        return {"job_id": job_id, "status": "queued"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/profiles/{profile_id}/events", dependencies=[Depends(require_admin)])
async def profile_events(profile_id: str) -> StreamingResponse:
    try:
        manager.get_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Profile not found") from exc
    return StreamingResponse(manager.profile_events(profile_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/jobs/{job_id}", response_model=JobStatus, dependencies=[Depends(require_admin)])
async def get_job(job_id: str) -> JobStatus:
    try:
        return manager.status(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@app.get("/api/jobs", response_model=list[JobSummary], dependencies=[Depends(require_admin)])
async def list_jobs(limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    return manager.list_jobs(limit)


@app.get("/api/jobs/{job_id}/events", dependencies=[Depends(require_admin)])
async def job_events(job_id: str) -> StreamingResponse:
    try:
        manager.status(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    return StreamingResponse(manager.events(job_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(require_admin)])
async def cancel_job(job_id: str) -> dict[str, str]:
    try:
        manager.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    return {"job_id": job_id, "status": "cancellation_requested"}


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(require_admin)])
async def delete_job(job_id: str) -> dict[str, str]:
    try:
        result = manager.delete_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    if result == "cancellation_requested":
        return {"job_id": job_id, "status": result}
    return {"job_id": job_id, "status": "deleted"}


@app.get("/api/jobs/{job_id}/files", response_model=list[JobFile], dependencies=[Depends(require_admin)])
async def list_files(job_id: str) -> list[dict]:
    try:
        return manager.files(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@app.get("/api/jobs/{job_id}/files/{file_id:path}", dependencies=[Depends(require_admin)])
async def download_file(job_id: str, file_id: str) -> FileResponse:
    try:
        row = manager.db.get_job(job_id)
    except Exception:
        row = None
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    root = settings.download_root.resolve()
    path = (root / file_id).resolve()
    if root not in path.parents or not path.is_file() or path.name.endswith((".part", ".ytdl")):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
