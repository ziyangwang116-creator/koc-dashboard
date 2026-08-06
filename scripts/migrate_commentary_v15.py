from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.koc_repository import KOCRepository
from database.db import connect
from models.enums import CreatorCategory


DATABASE_PATH = PROJECT_ROOT / "data" / "koc.db"
EFFECTIVE_DATE = date(2026, 7, 1)

COMMENTARY_CONTRACTS = {
    6: {
        "contract": "YTB长+YTBshorts",
    },
    7: {
        "contract": "YTB长+YTBshorts",
    },
    8: {
        "contract": "YTB长+YTBshorts",
    },
    9: {
        "contract": "YTB长+TT",
        "youtube_user_id": "10468899",
        "youtube_homepage_url": "https://www.youtube.com/@Paripinnnn",
        "tiktok_user_id": "22195549",
    },
    10: {
        "contract": "YTB长+TT",
        "youtube_user_id": "16001100",
        "youtube_homepage_url": "https://www.youtube.com/@nmkrgame",
        "tiktok_user_id": "6143965",
    },
}


def _rename_grassroot_contract(value: str) -> str:
    text = value.strip()
    compact = text.casefold().replace(" ", "")
    if "ytb" not in compact or "short" in compact or "长直" in compact:
        return text
    if compact in {"ytb", "4月ytb", "5月ytb"}:
        return f"{text}长直"
    return text


def _update_contract(
    repository: KOCRepository,
    record_id: int,
    *,
    contract_types: list[str],
    category: CreatorCategory,
    youtube_user_id: str | None = None,
    youtube_homepage_url: str | None = None,
    tiktok_user_id: str | None = None,
) -> dict[str, object]:
    current = repository.get(record_id)
    if current is None:
        raise RuntimeError(f"Creator {record_id} does not exist.")
    preserved_end = current.contract_end_date
    if preserved_end is None:
        raise RuntimeError(f"Creator {record_id} has no contract end date.")
    repository.update(
        record_id,
        user_id=current.user_id,
        koc_name=current.koc_name,
        creator_category=category,
        contract_types=contract_types,
        homepage_url=current.homepage_url,
        follower_count=current.follower_count,
        youtube_user_id=(
            youtube_user_id
            if youtube_user_id is not None
            else current.youtube_user_id
        ),
        youtube_homepage_url=(
            youtube_homepage_url
            if youtube_homepage_url is not None
            else current.youtube_homepage_url
        ),
        youtube_follower_count=current.youtube_follower_count,
        tiktok_user_id=(
            tiktok_user_id
            if tiktok_user_id is not None
            else current.tiktok_user_id
        ),
        tiktok_homepage_url=current.tiktok_homepage_url,
        tiktok_follower_count=current.tiktok_follower_count,
        active=current.active,
        note=current.note,
        effective_date=EFFECTIVE_DATE,
        contract_start_date=EFFECTIVE_DATE,
        contract_end_date=preserved_end,
    )
    repository.update_contract_period(
        record_id,
        source_effective_date=EFFECTIVE_DATE,
        contract_types=contract_types,
        contract_start_date=EFFECTIVE_DATE,
        contract_end_date=preserved_end,
    )
    updated = repository.get(record_id)
    if updated is None:
        raise RuntimeError(f"Creator {record_id} could not be reloaded.")
    return {
        "id": updated.id,
        "name": updated.koc_name,
        "contract_types": updated.contract_types,
        "contract_start_date": updated.contract_start_date.isoformat(),
        "contract_end_date": updated.contract_end_date.isoformat(),
        "youtube_user_id": updated.youtube_user_id,
        "youtube_homepage_url": updated.youtube_homepage_url,
        "youtube_follower_count": updated.youtube_follower_count,
        "tiktok_user_id": updated.tiktok_user_id,
        "tiktok_homepage_url": updated.tiktok_homepage_url,
        "tiktok_follower_count": updated.tiktok_follower_count,
    }


def _close_previous_contract(repository: KOCRepository, record_id: int) -> None:
    previous = [
        snapshot
        for snapshot in repository.list_profile_history_for_creator(record_id)
        if snapshot.effective_date < EFFECTIVE_DATE
    ]
    if not previous:
        return
    source = max(previous, key=lambda snapshot: snapshot.effective_date)
    start = source.contract_start_date or source.effective_date
    repository.update_contract_period(
        record_id,
        source_effective_date=source.effective_date,
        contract_types=source.contract_types,
        contract_start_date=start,
        contract_end_date=date(2026, 6, 30),
    )


def _sync_platform_uids(
    repository: KOCRepository,
    record_id: int,
    *,
    youtube_user_id: str | None,
    tiktok_user_id: str | None,
) -> None:
    with connect(repository.database_path) as connection:
        connection.execute(
            """
            UPDATE creator_profile_history
            SET youtube_user_id = ?, tiktok_user_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE creator_id = ?
            """,
            (youtube_user_id, tiktok_user_id, record_id),
        )


def main() -> None:
    repository = KOCRepository(DATABASE_PATH)
    changed: list[dict[str, object]] = []
    for record_id, config in COMMENTARY_CONTRACTS.items():
        updated = _update_contract(
            repository,
            record_id,
            contract_types=[str(config["contract"])],
            category=CreatorCategory.COMMENTARY,
            youtube_user_id=config.get("youtube_user_id"),
            youtube_homepage_url=config.get("youtube_homepage_url"),
            tiktok_user_id=config.get("tiktok_user_id"),
        )
        changed.append(updated)
        _close_previous_contract(repository, record_id)
        _sync_platform_uids(
            repository,
            record_id,
            youtube_user_id=(
                str(updated["youtube_user_id"])
                if updated.get("youtube_user_id") is not None
                else None
            ),
            tiktok_user_id=(
                str(updated["tiktok_user_id"])
                if updated.get("tiktok_user_id") is not None
                else None
            ),
        )

    commentary_ids = set(COMMENTARY_CONTRACTS)
    for record in repository.list(include_inactive=True):
        if record.id in commentary_ids:
            continue
        if CreatorCategory.GRASSROOT not in record.creator_categories:
            continue
        if (
            record.contract_end_date is not None
            and record.contract_end_date < EFFECTIVE_DATE
        ):
            continue
        renamed = [_rename_grassroot_contract(value) for value in record.contract_types]
        if tuple(renamed) == record.contract_types:
            continue
        changed.append(
            _update_contract(
                repository,
                record.id,
                contract_types=renamed,
                category=CreatorCategory.GRASSROOT,
            )
        )

    print(json.dumps(changed, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
