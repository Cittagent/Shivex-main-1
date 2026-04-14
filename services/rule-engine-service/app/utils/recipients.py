"""Recipient normalization helpers for notification channels."""

from __future__ import annotations

import re

_PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def normalize_phone_recipient(value: str) -> str:
    """Normalize a phone recipient into E.164-like format."""
    cleaned = "".join(ch for ch in value.strip() if ch.isdigit() or ch == "+")
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    if not cleaned.startswith("+"):
        cleaned = f"+{cleaned}"
    digits = cleaned[1:]
    if not digits.isdigit() or len(digits) < 8 or len(digits) > 15:
        raise ValueError("phone recipient must be an E.164-compatible phone number")
    if not _PHONE_RE.match(cleaned):
        raise ValueError("phone recipient must be an E.164-compatible phone number")
    return cleaned
