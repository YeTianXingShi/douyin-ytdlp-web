from __future__ import annotations

from urllib.parse import quote

from .vendor.abogus import ABogus


def make_a_bogus(params: dict[str, object]) -> str:
    """Generate the signed parameter with the bundled adapter."""
    return quote(ABogus().get_value(params), safe="")
