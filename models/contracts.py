from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from models.enums import CreatorCategory


_CATEGORY_BY_CONTRACT_TEXT: dict[str, CreatorCategory] = {
    "长包": CreatorCategory.LONG_TERM,
    "long_term": CreatorCategory.LONG_TERM,
    "解说": CreatorCategory.COMMENTARY,
    "commentary": CreatorCategory.COMMENTARY,
    "ytb长+tt": CreatorCategory.COMMENTARY,
    "ytb长+ytbshorts": CreatorCategory.COMMENTARY,
    "ytb长+ytb shorts": CreatorCategory.COMMENTARY,
    "ytb": CreatorCategory.GRASSROOT,
    "ytb shorts": CreatorCategory.GRASSROOT,
    "ytb_shorts": CreatorCategory.GRASSROOT,
    "tt": CreatorCategory.GRASSROOT,
    "4月ytb": CreatorCategory.GRASSROOT,
    "april_ytb": CreatorCategory.GRASSROOT,
    "4月tt": CreatorCategory.GRASSROOT,
    "5月ytb": CreatorCategory.GRASSROOT,
    "may_ytb": CreatorCategory.GRASSROOT,
    "5月tt": CreatorCategory.GRASSROOT,
    "may_tt": CreatorCategory.GRASSROOT,
}


def contract_texts_for_category(category: CreatorCategory) -> tuple[str, ...]:
    """Return every persisted contract label that belongs to a category."""
    return tuple(
        contract_text
        for contract_text, mapped_category in _CATEGORY_BY_CONTRACT_TEXT.items()
        if mapped_category is category
    )


def normalize_contract_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    text = str(value).strip()
    return text or None


def contract_category(value: object) -> CreatorCategory | None:
    text = normalize_contract_text(value)
    if text is None:
        return None
    category = _CATEGORY_BY_CONTRACT_TEXT.get(text.casefold())
    if category is not None:
        return category
    compact = text.casefold().replace(" ", "")
    if "ytb" in compact or "tiktok" in compact or "tt" in compact:
        return CreatorCategory.GRASSROOT
    return None


def derive_creator_categories(
    contract_types: Iterable[object],
    fallback: CreatorCategory | None = None,
) -> tuple[CreatorCategory, ...]:
    categories: list[CreatorCategory] = []
    for contract_type in contract_types:
        category = contract_category(contract_type)
        if category is not None and category not in categories:
            categories.append(category)
    if not categories and fallback is not None:
        categories.append(fallback)
    return tuple(categories)
