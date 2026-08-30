from __future__ import annotations

import asyncio
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import parse_qs, urlparse

import httpx

from .abogus_adapter import make_a_bogus
from .config import Settings
from .cookie_provider import CookieProvider


VIDEO_TYPES = {0, 4}
IMAGE_TYPES = {2, 68}


@dataclass(frozen=True)
class DouyinPost:
    aweme_id: str
    aweme_type: int | None
    title: str | None
    upload_date: str | None = None
    author_name: str | None = None


class ProfileService:
    endpoint = "https://www.douyin.com/aweme/v1/web/aweme/post/"
    profile_endpoint = "https://www.douyin.com/aweme/v1/web/user/profile/other/"

    def __init__(self, settings: Settings, cookies: CookieProvider):
        self.settings = settings
        self.cookies = cookies

    @staticmethod
    def _validate_host(host: str | None) -> bool:
        host = (host or "").lower().split(":", 1)[0]
        return host == "douyin.com" or host.endswith(".douyin.com")

    async def resolve_sec_user_id(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        if not self._validate_host(parsed.hostname):
            raise ValueError("Only douyin.com URLs are supported")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0].lower() == "user" and parts[1]:
            return parts[1]
        if parsed.hostname == "v.douyin.com":
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self.settings.request_timeout,
                proxy=self.settings.proxy,
                headers={"User-Agent": self.settings.user_agent},
            ) as client:
                response = await client.get(source_url)
                response.raise_for_status()
                final = urlparse(str(response.url))
                query_id = parse_qs(final.query).get("sec_uid", [None])[0]
                if query_id:
                    return query_id
                parts = [part for part in final.path.split("/") if part]
                if len(parts) >= 2 and parts[0].lower() == "user":
                    return parts[1]
        raise ValueError("Unable to resolve sec_user_id from the profile URL")

    def _params(self, sec_user_id: str, max_cursor: int) -> dict[str, object]:
        random_token = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(126)) + "=="
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": 1,
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": 1920,
            "screen_height": 1080,
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "130.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "130.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": 12,
            "device_memory": 8,
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "from_user_page": "1",
            "locate_query": "false",
            "need_time_list": "1",
            "pc_libra_divert": "Windows",
            "publish_video_strategy_type": "2",
            "round_trip_time": "0",
            "show_live_replay_strategy": "1",
            "time_list_query": "0",
            "whale_cut_token": "",
            "update_version_code": "170400",
            "msToken": random_token,
            "sec_user_id": sec_user_id,
            "max_cursor": max_cursor,
            "count": self.settings.page_size,
        }

    async def fetch_profile_name(self, sec_user_id: str) -> str | None:
        """Best-effort nickname lookup used when a profile is first added."""
        try:
            cookie_header = self.cookies.cookie_header()
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Cookie": cookie_header,
                "Referer": f"https://www.douyin.com/user/{sec_user_id}",
                "User-Agent": self.settings.user_agent,
            }
            params = self._params(sec_user_id, 0)
            params.pop("max_cursor", None)
            params.pop("count", None)
            params["a_bogus"] = make_a_bogus(params, self.settings.reference_repo_dir)
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout,
                proxy=self.settings.proxy,
                headers=headers,
            ) as client:
                response = await client.get(self.profile_endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, RuntimeError):
            return None

        def find_name(value: object) -> str | None:
            if isinstance(value, dict):
                for key in ("nickname", "display_name"):
                    candidate = value.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()
                for nested in value.values():
                    found = find_name(nested)
                    if found:
                        return found
            elif isinstance(value, list):
                for nested in value:
                    found = find_name(nested)
                    if found:
                        return found
            return None

        return find_name(payload)

    async def iter_posts(self, source_url: str, max_items: int = 0) -> AsyncIterator[DouyinPost]:
        sec_user_id = await self.resolve_sec_user_id(source_url)
        cookie_header = self.cookies.cookie_header()
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": cookie_header,
            "Referer": "https://www.douyin.com/",
            "User-Agent": self.settings.user_agent,
        }
        cursor = 0
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        yielded = 0
        async with httpx.AsyncClient(
            timeout=self.settings.request_timeout,
            proxy=self.settings.proxy,
            headers=headers,
        ) as client:
            while True:
                params = self._params(sec_user_id, cursor)
                params["a_bogus"] = make_a_bogus(params, self.settings.reference_repo_dir)
                try:
                    response = await client.get(self.endpoint, params=params)
                    response.raise_for_status()
                    payload = response.json()
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status == 429:
                        raise RuntimeError("Douyin rate limit (429); retry later") from exc
                    if status == 403:
                        raise RuntimeError("Douyin profile request denied (403); Cookie may be expired, rate-limited, or blocked by risk control. Refresh Chrome Cookie and try later") from exc
                    raise RuntimeError(f"Douyin profile request failed ({status})") from exc
                except (httpx.HTTPError, ValueError) as exc:
                    raise RuntimeError("Douyin profile response could not be read") from exc

                if not isinstance(payload, dict) or not isinstance(payload.get("aweme_list"), list):
                    raise RuntimeError("Douyin profile response schema is unknown (aweme_list missing)")
                raw_items = payload["aweme_list"]
                page_ids = tuple(str(item.get("aweme_id") or item.get("aweme_id_str")) for item in raw_items if isinstance(item, dict))
                if page_ids in seen_pages:
                    raise RuntimeError("Douyin profile returned a repeated page")
                seen_pages.add(page_ids)
                if not raw_items:
                    return

                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    aweme_id = str(item.get("aweme_id") or item.get("aweme_id_str") or "")
                    if not aweme_id or aweme_id in seen_ids:
                        continue
                    seen_ids.add(aweme_id)
                    aweme_type = item.get("aweme_type")
                    try:
                        aweme_type = int(aweme_type) if aweme_type is not None else None
                    except (TypeError, ValueError):
                        aweme_type = None
                    title = item.get("desc")
                    if not isinstance(title, str):
                        title = None
                    author_name = None
                    author = item.get("author")
                    if isinstance(author, dict):
                        for key in ("nickname", "display_name", "unique_id"):
                            value = author.get(key)
                            if isinstance(value, str) and value.strip():
                                author_name = value.strip()
                                break
                    upload_date = item.get("create_time")
                    try:
                        upload_date = datetime.fromtimestamp(int(upload_date), tz=timezone.utc).strftime("%Y%m%d") if upload_date else None
                    except Exception:
                        upload_date = None
                    if aweme_type in IMAGE_TYPES:
                        yield DouyinPost(aweme_id, aweme_type, title, upload_date, author_name)
                    elif aweme_type in VIDEO_TYPES or aweme_type is None:
                        yield DouyinPost(aweme_id, aweme_type, title, upload_date, author_name)
                    else:
                        yield DouyinPost(aweme_id, aweme_type, title, upload_date, author_name)
                    yielded += 1
                    if max_items and yielded >= max_items:
                        return

                next_cursor = payload.get("max_cursor")
                has_more = payload.get("has_more")
                try:
                    next_cursor = int(next_cursor)
                except (TypeError, ValueError):
                    raise RuntimeError("Douyin profile response schema is unknown (max_cursor missing)")
                if not bool(has_more) or next_cursor == cursor:
                    return
                cursor = next_cursor
                await asyncio.sleep(max(0.0, self.settings.request_delay))
