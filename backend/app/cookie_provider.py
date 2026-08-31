from __future__ import annotations

import http.cookiejar
import os
import shutil
import tempfile
from pathlib import Path


class CookieProvider:
    def __init__(self, cookie_file: Path):
        self.source_file = cookie_file
        self.cookie_file = cookie_file
        self._runtime_file: Path | None = None

    def prepare(self) -> None:
        """Copy read-only Docker Secrets to a writable private temp file."""
        self.validate()
        file_descriptor, runtime_name = tempfile.mkstemp(
            prefix="douyin-ytdlp-cookies-", suffix=".txt"
        )
        os.close(file_descriptor)
        runtime_file = Path(runtime_name)
        try:
            shutil.copyfile(self.source_file, runtime_file)
            os.chmod(runtime_file, 0o600)
        except OSError as exc:
            runtime_file.unlink(missing_ok=True)
            raise RuntimeError("Cookie file cannot be prepared") from exc
        self._runtime_file = runtime_file
        self.cookie_file = runtime_file

    def cleanup(self) -> None:
        if self._runtime_file:
            self._runtime_file.unlink(missing_ok=True)
            self._runtime_file = None
            self.cookie_file = self.source_file

    def validate(self) -> None:
        if not self.cookie_file.is_file():
            raise RuntimeError(f"Cookie file not found: {self.cookie_file}")
        try:
            first_line = self.cookie_file.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        except (IndexError, OSError) as exc:
            raise RuntimeError("Cookie file cannot be read") from exc
        if "Netscape" not in first_line and "HTTP Cookie File" not in first_line:
            raise RuntimeError("Cookie file must be in Netscape/Mozilla format")

    def cookie_header(self) -> str:
        self.validate()
        jar = http.cookiejar.MozillaCookieJar(str(self.cookie_file))
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception as exc:
            raise RuntimeError("Cookie file is not a valid Netscape cookie file") from exc
        pairs = []
        for cookie in jar:
            domain = cookie.domain.lstrip(".").lower()
            if domain == "douyin.com" or domain.endswith(".douyin.com"):
                pairs.append(f"{cookie.name}={cookie.value}")
        if not pairs:
            raise RuntimeError("Cookie file has no douyin.com cookies")
        return "; ".join(pairs)
