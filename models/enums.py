from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CreatorCategory(StrEnum):
    LONG_TERM = "LONG_TERM"
    COMMENTARY = "COMMENTARY"
    GRASSROOT = "GRASSROOT"


class ContractType(StrEnum):
    YTB = "YTB"
    YTB_SHORTS = "YTB_SHORTS"
    TT = "TT"
    APRIL_YTB = "APRIL_YTB"
    APRIL_TT = "APRIL_TT"
    MAY_YTB = "MAY_YTB"
    MAY_TT = "MAY_TT"


class FollowerSyncStatus(StrEnum):
    NEVER = "NEVER"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    MANUAL = "MANUAL"


class FollowerSource(StrEnum):
    YOUTUBE_API = "YOUTUBE_API"
    TIKTOK_API = "TIKTOK_API"
    TIKTOK_BROWSER = "TIKTOK_BROWSER"
    MANUAL = "MANUAL"


class OperatorMode(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL_ASSISTED = "MANUAL_ASSISTED"
    MANUAL = "MANUAL"


CREATOR_CATEGORY_LABELS: dict[CreatorCategory, str] = {
    CreatorCategory.LONG_TERM: "长包",
    CreatorCategory.COMMENTARY: "解说",
    CreatorCategory.GRASSROOT: "草根",
}

CONTRACT_TYPE_LABELS: dict[ContractType, str] = {
    ContractType.YTB: "YTB",
    ContractType.YTB_SHORTS: "YTB shorts",
    ContractType.TT: "TT",
    ContractType.APRIL_YTB: "4月YTB",
    ContractType.APRIL_TT: "4月TT",
    ContractType.MAY_YTB: "5月YTB",
    ContractType.MAY_TT: "5月TT",
}

FOLLOWER_SYNC_STATUS_LABELS: dict[FollowerSyncStatus, str] = {
    FollowerSyncStatus.NEVER: "从未更新",
    FollowerSyncStatus.SUCCESS: "自动更新成功",
    FollowerSyncStatus.FAILED: "自动更新失败",
    FollowerSyncStatus.MANUAL: "人工填写",
}

FOLLOWER_SOURCE_LABELS: dict[FollowerSource, str] = {
    FollowerSource.YOUTUBE_API: "YouTube 官方 API",
    FollowerSource.TIKTOK_API: "TikTok-Api",
    FollowerSource.TIKTOK_BROWSER: "TikTok 本地登录浏览器",
    FollowerSource.MANUAL: "人工填写",
}

_CREATOR_CATEGORY_BY_LABEL = {
    label.casefold(): value for value, label in CREATOR_CATEGORY_LABELS.items()
}
_CONTRACT_TYPE_BY_LABEL = {
    label.casefold(): value for value, label in CONTRACT_TYPE_LABELS.items()
}


@dataclass(frozen=True)
class ContractMetadata:
    platform_family: str
    content_family: str


_CONTRACT_METADATA: dict[ContractType, ContractMetadata] = {
    ContractType.YTB: ContractMetadata("YouTube", "long_livestream"),
    ContractType.APRIL_YTB: ContractMetadata("YouTube", "long_livestream"),
    ContractType.MAY_YTB: ContractMetadata("YouTube", "long_livestream"),
    ContractType.YTB_SHORTS: ContractMetadata("YouTube", "shorts"),
    ContractType.TT: ContractMetadata("TikTok", "shorts"),
    ContractType.APRIL_TT: ContractMetadata("TikTok", "shorts"),
    ContractType.MAY_TT: ContractMetadata("TikTok", "shorts"),
}


def get_contract_metadata(
    contract_type: ContractType | str | None,
) -> ContractMetadata | None:
    if contract_type is None or contract_type == "":
        return None
    return _CONTRACT_METADATA[ContractType(contract_type)]


def parse_creator_category(value: CreatorCategory | str | None) -> CreatorCategory | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, CreatorCategory):
        return value
    text = str(value).strip()
    return _CREATOR_CATEGORY_BY_LABEL.get(text.casefold()) or CreatorCategory(
        text.upper()
    )


def parse_contract_type(value: ContractType | str | None) -> ContractType | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, ContractType):
        return value
    text = str(value).strip()
    return _CONTRACT_TYPE_BY_LABEL.get(text.casefold()) or ContractType(text.upper())
