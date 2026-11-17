"""AI disclosure (EU AI Act Article 50): callers are told up front that they are talking to an AI.

The text comes from AI_DISCLOSURE. Blanking it does NOT switch it off: that only happens when
AI_DISCLOSURE_REMOVED_BY_WRITTEN_REQUEST holds a reference to the client's written request
(date and who asked). Without that reference an empty value falls back to the default.
"""
from __future__ import annotations

from typing import Optional

DEFAULT_DISCLOSURE = "Hi, this is {name}, an AI assistant for {business}."
DEFAULT_HANDOVER = "I'm an AI assistant, so I'm handing you over to a person on the team."


def _fill(text: str, name: str, business: str) -> str:
    return text.replace("{name}", name).replace("{business}", business).strip()


def resolve_disclosure(text: Optional[str], removed_by_written_request: Optional[str],
                       name: str, business: str) -> str:
    """The opening disclosure line. Empty only when a written-request reference is recorded."""
    if (removed_by_written_request or "").strip():
        return _fill(text or "", name, business)
    return _fill((text or "").strip() or DEFAULT_DISCLOSURE, name, business)


def handover_notice(removed_by_written_request: Optional[str]) -> str:
    """What the caller hears when they are passed to a person."""
    return "" if (removed_by_written_request or "").strip() else DEFAULT_HANDOVER
