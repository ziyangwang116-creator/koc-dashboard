from database.koc_repository import KOCRepository
from models.enums import CreatorCategory, FollowerSource, FollowerSyncStatus
from services.koc_service import KOCService


def test_manual_follower_update_records_a_manual_refresh_even_when_value_is_unchanged(
    tmp_path,
):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="manual-1",
        koc_name="manual creator",
        creator_category=CreatorCategory.GRASSROOT,
        contract_types=["TT"],
        follower_count=12_345,
    )

    updated = KOCService(repository).update_follower_count_manually(
        record.id,
        12_345,
    )

    assert updated.follower_count == 12_345
    assert updated.follower_sync_status is FollowerSyncStatus.MANUAL
    assert updated.follower_source is FollowerSource.MANUAL
    assert updated.follower_count_updated_at is not None
