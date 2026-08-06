from __future__ import annotations

import re
from typing import Any

import pandas as pd


DECIMAL_INTEGER_PATTERN = re.compile(r"^([+-]?\d+)\.0+$")


def normalize_user_id(value: Any) -> str | None:
    """Normalize Excel UID values without losing their textual identity."""
    if value is None or pd.isna(value):
        return None

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    text = str(value).strip()
    if not text:
        return None

    decimal_match = DECIMAL_INTEGER_PATTERN.fullmatch(text)
    if decimal_match:
        return decimal_match.group(1)
    return text
