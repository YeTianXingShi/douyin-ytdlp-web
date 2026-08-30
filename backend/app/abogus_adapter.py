from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote


def make_a_bogus(params: dict[str, object], reference_repo_dir: Path) -> str:
    """Use the reference project's pure-Python A-Bogus implementation.

    The import is intentionally isolated from the reference project's config module so
    its hard-coded Cookie configuration is never loaded by this application.
    """
    module_root = reference_repo_dir.resolve()
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))
    try:
        from crawlers.douyin.web.abogus import ABogus
    except ImportError as exc:
        raise RuntimeError(
            "A-Bogus dependency is unavailable; check REFERENCE_REPO_DIR and gmssl"
        ) from exc
    return quote(ABogus().get_value(params), safe="")
