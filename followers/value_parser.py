from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class FollowerValueError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedFollowerValue:
    follower_count: int
    raw_display_value: str
    is_estimated: bool


_EXACT_INTEGER = re.compile(r"^(?:\d+|\d{1,3}(?:,\d{3})+)$")
_ABBREVIATED = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(百万|万|K|M)$",
    flags=re.IGNORECASE,
)
_MULTIPLIERS = {
    "K": Decimal("1000"),
    "M": Decimal("1000000"),
    "万": Decimal("10000"),
    "百万": Decimal("1000000"),
}


def parse_follower_display_value(value: object) -> ParsedFollowerValue:
    raw = str(value).strip() if value is not None else ""
    if not raw:
        raise FollowerValueError("粉丝数展示值不能为空。")
    compact = raw.replace(" ", "")
    if _EXACT_INTEGER.fullmatch(compact):
        count = int(compact.replace(",", ""))
        return ParsedFollowerValue(count, raw, False)

    match = _ABBREVIATED.fullmatch(compact)
    if match is None:
        raise FollowerValueError("无法可靠解析该粉丝数展示值。")
    number_text, unit_text = match.groups()
    unit = unit_text.upper() if unit_text.upper() in {"K", "M"} else unit_text
    try:
        converted = Decimal(number_text) * _MULTIPLIERS[unit]
    except (InvalidOperation, KeyError) as exc:
        raise FollowerValueError("无法可靠解析该粉丝数展示值。") from exc
    if converted != converted.to_integral_value() or converted < 0:
        raise FollowerValueError("无法可靠解析该粉丝数展示值。")
    return ParsedFollowerValue(int(converted), raw, True)
