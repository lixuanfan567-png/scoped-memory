"""Versioned, bounded transport for memory facts.

The codebook is fixed by SMC/1 and documented in the skill reference. The wire
packet contains each fact once; it is not an authorization token.
"""

from __future__ import annotations

import json
from typing import Any


FORMAT = "SMC/1"
SCOPE_CODES = {"user": "u", "project": "p", "session": "t"}


def encode_item(item: dict[str, Any]) -> list[str]:
    return [
        SCOPE_CODES[item["scope"]], item["topic"], item["content"],
        item["event_id"], item["project_id"] or "",
        "i" if item["source"] == "inherited" else "c",
    ]


def payload(rows: list[list[str]], truncated: bool) -> dict[str, Any]:
    return {"v": FORMAT, "r": rows, "more": truncated}


def render(rows: list[list[str]], truncated: bool) -> str:
    return json.dumps(payload(rows, truncated), ensure_ascii=False, separators=(",", ":"))


def compact_packet(items: list[dict[str, Any]], token_budget: int, estimate) -> dict[str, Any]:
    """Fit records to a measured budget; never emit a partial fact or duplicate it."""
    rows: list[list[str]] = []
    clipped = False
    for item in items:
        row = encode_item(item)
        if estimate(render([*rows, row], len(rows) + 1 < len(items))) > token_budget:
            if not rows:
                low, high, best = 0, len(row[2]), None
                while low <= high:
                    middle = (low + high) // 2
                    partial = [*row[:2], row[2][:middle], *row[3:], "x"]
                    if estimate(render([partial], True)) <= token_budget:
                        best = partial
                        low = middle + 1
                    else:
                        high = middle - 1
                if best is not None:
                    rows.append(best)
                    clipped = True
                    break
            continue
        rows.append(row)
    truncated = clipped or len(rows) < len(items)
    packet = render(rows, truncated)
    if estimate(packet) > token_budget:
        # The fixed envelope itself must fit. The smallest allowed budget does.
        raise ValueError("token budget is too small for the compact envelope")
    return {"packet": payload(rows, truncated), "estimated_tokens": estimate(packet),
            "selected_items": len(rows), "available_items": len(items), "truncated": truncated}
