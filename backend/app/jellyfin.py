from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SEPARATORS = re.compile(r"[\\/:*?\"<>|]+")


def safe_component(value: str | None, fallback: str = "untitled", limit: int = 120) -> str:
    value = _CONTROL.sub("", str(value or "")).strip()
    value = _SEPARATORS.sub("_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value or value in {".", ".."}:
        value = fallback
    return value[:limit].rstrip(" .") or fallback


def profile_media_dir(download_root: Path, sec_user_id: str) -> Path:
    return download_root / "profiles" / safe_component(sec_user_id, "unknown-profile", 180)


def single_media_dir(download_root: Path, aweme_id: str) -> Path:
    return download_root / "single" / safe_component(aweme_id, "unknown-video", 180)


def episode_stem(post: Any) -> str:
    season = int(post["season_number"] or 0)
    episode = int(post["episode_number"] or 1)
    title = safe_component(post["title"], post["aweme_id"])
    return f"S{season:04d}E{episode:04d} - {title} [{post['aweme_id']}]"


def _text(parent: Element, name: str, value: Any) -> None:
    if value is not None and str(value) != "":
        SubElement(parent, name).text = str(value)


def _write_xml(path: Path, root: Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + tostring(root, encoding="utf-8")
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def write_profile_nfo(profile: Any, path: Path) -> None:
    root = Element("tvshow")
    name = profile["display_name"] or profile["sec_user_id"]
    _text(root, "title", name)
    _text(root, "sorttitle", name)
    _text(root, "plot", "抖音用户主页")
    _text(root, "studio", "抖音")
    _text(root, "genre", "Douyin")
    _text(root, "tag", "抖音")
    _text(root, "tag", name)
    unique = SubElement(root, "uniqueid", {"type": "douyin", "default": "true"})
    unique.text = profile["sec_user_id"]
    _text(root, "website", profile["profile_url"])
    _text(root, "dateadded", profile["created_at"])
    _write_xml(path, root)


def write_season_nfo(profile: Any, season: int, path: Path) -> None:
    root = Element("season")
    name = profile["display_name"] or profile["sec_user_id"]
    _text(root, "title", str(season) if season else "未知日期")
    _text(root, "seasonnumber", season)
    _text(root, "showtitle", name)
    unique = SubElement(root, "uniqueid", {"type": "douyin-season", "default": "true"})
    unique.text = f"{profile['sec_user_id']}-{season}"
    _write_xml(path, root)


def write_episode_nfo(profile: Any, post: Any, path: Path) -> None:
    root = Element("episodedetails")
    name = profile["display_name"] or profile["sec_user_id"]
    title = post["title"] or post["aweme_id"]
    _text(root, "title", title)
    _text(root, "originaltitle", title)
    _text(root, "showtitle", name)
    _text(root, "season", post["season_number"])
    _text(root, "episode", post["episode_number"])
    _text(root, "aired", post["aired_date"] or post["upload_date"])
    _text(root, "premiered", post["aired_date"] or post["upload_date"])
    if post["upload_date"]:
        _text(root, "year", str(post["upload_date"])[:4])
    if post["duration"]:
        _text(root, "runtime", max(1, round(float(post["duration"]) / 60)))
        _text(root, "durationinseconds", post["duration"])
    _text(root, "plot", post["description"] or title)
    _text(root, "studio", "抖音")
    _text(root, "genre", "Douyin")
    _text(root, "tag", "短视频")
    _text(root, "tag", name)
    actor = SubElement(root, "actor")
    _text(actor, "name", post["channel"] or name)
    _text(actor, "role", "Uploader")
    unique = SubElement(root, "uniqueid", {"type": "douyin", "default": "true"})
    unique.text = post["aweme_id"]
    if post["thumbnail_file"]:
        _text(root, "thumb", Path(post["thumbnail_file"]).name)
    fileinfo = SubElement(root, "fileinfo")
    streams = SubElement(fileinfo, "streamdetails")
    video = SubElement(streams, "video")
    _text(video, "codec", post["vcodec"])
    _text(video, "width", post["width"])
    _text(video, "height", post["height"])
    _text(video, "fps", post["fps"])
    _text(video, "durationinseconds", post["duration"])
    audio = SubElement(streams, "audio")
    _text(audio, "codec", post["acodec"])
    custom = SubElement(root, "douyin")
    for key in ("aweme_id", "channel", "channel_id", "channel_url", "uploader", "uploader_id", "uploader_url", "view_count", "like_count", "comment_count", "repost_count", "save_count", "track", "album", "availability", "video_url"):
        value = post[key] if key in post.keys() else None
        if key == "aweme_id":
            tag = "awemeid"
        else:
            tag = key
        _text(custom, tag, value)
    artists = post["artists_json"]
    if artists:
        try:
            for artist in json.loads(artists):
                _text(custom, "artist", artist)
        except (TypeError, ValueError):
            _text(custom, "artist", artists)
    _write_xml(path, root)


def write_movie_nfo(post: Any, path: Path) -> None:
    root = Element("movie")
    title = post["title"] or post["aweme_id"]
    _text(root, "title", title)
    _text(root, "originaltitle", title)
    _text(root, "plot", post["description"] or title)
    _text(root, "studio", "抖音")
    _text(root, "genre", "Douyin")
    _text(root, "premiered", post["upload_date"])
    _text(root, "year", str(post["upload_date"])[:4] if post["upload_date"] else None)
    _text(root, "runtime", max(1, round(float(post["duration"]) / 60)) if post["duration"] else None)
    unique = SubElement(root, "uniqueid", {"type": "douyin", "default": "true"})
    unique.text = post["aweme_id"]
    if post["thumbnail_file"]:
        _text(root, "thumb", Path(post["thumbnail_file"]).name)
    _text(root, "website", post["video_url"])
    _write_xml(path, root)


def download_image(urls: Iterable[str], destination: Path, headers: dict[str, str], timeout: float = 20.0) -> tuple[Path | None, str | None]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    for url in urls:
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            continue
        try:
            with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout) as client:
                response = client.get(url)
                response.raise_for_status()
                if not response.content or len(response.content) > 20 * 1024 * 1024:
                    continue
                content_type = response.headers.get("content-type", "").lower()
                extension = ".jpg"
                if "png" in content_type:
                    extension = ".png"
                elif "webp" in content_type:
                    extension = ".webp"
                elif "gif" in content_type:
                    extension = ".gif"
                final = destination.with_suffix(extension)
                digest = hashlib.sha256(response.content).hexdigest()
                with tempfile.NamedTemporaryFile("wb", dir=final.parent, prefix=f".{final.name}.", delete=False) as handle:
                    handle.write(response.content)
                    temporary = Path(handle.name)
                temporary.replace(final)
                return final, digest
        except (httpx.HTTPError, OSError):
            continue
    return None, "artwork_download_failed"
