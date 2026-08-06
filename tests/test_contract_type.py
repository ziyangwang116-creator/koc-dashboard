import pytest

from database.koc_repository import KOCRepository, KOCRepositoryError
from models.enums import (
    ContractType,
    CreatorCategory,
    get_contract_metadata,
)


def test_all_creator_categories_are_supported():
    assert {value.value for value in CreatorCategory} == {
        "LONG_TERM",
        "COMMENTARY",
        "GRASSROOT",
    }


@pytest.mark.parametrize("contract", list(ContractType))
def test_grassroot_creator_accepts_every_contract_type(tmp_path, contract):
    repository = KOCRepository(tmp_path / f"{contract.value}.db")
    record = repository.create(
        user_id=f"uid-{contract.value}",
        koc_name="草根达人",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=contract,
    )
    assert record.contract_type is contract


def test_contract_type_can_switch_without_changing_identity(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(
        user_id="switch-uid",
        koc_name="切换达人",
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.YTB,
    )

    updated = repository.update(
        record.id,
        user_id=record.user_id,
        koc_name=record.koc_name,
        creator_category=CreatorCategory.GRASSROOT,
        contract_type=ContractType.MAY_YTB,
        homepage_url=None,
        follower_count=None,
        active=True,
        note=None,
    )

    assert updated.user_id == "switch-uid"
    assert updated.koc_name == "切换达人"
    assert updated.contract_type is ContractType.MAY_YTB
    assert updated.updated_at != record.updated_at


@pytest.mark.parametrize(
    "category", [CreatorCategory.LONG_TERM, CreatorCategory.COMMENTARY]
)
def test_non_grassroot_creator_allows_empty_contract(tmp_path, category):
    repository = KOCRepository(tmp_path / f"{category.value}.db")
    record = repository.create(
        user_id=category.value, koc_name="达人", creator_category=category
    )
    assert record.contract_type is None


def test_non_grassroot_contract_is_rejected(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    with pytest.raises(KOCRepositoryError, match="只有草根"):
        repository.create(
            user_id="bad-category",
            koc_name="达人",
            creator_category=CreatorCategory.LONG_TERM,
            contract_type=ContractType.TT,
        )


def test_illegal_contract_type_is_rejected(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    with pytest.raises(KOCRepositoryError, match="合同类型"):
        repository.create(
            user_id="bad-contract",
            koc_name="达人",
            creator_category=CreatorCategory.GRASSROOT,
            contract_type="NOT_ALLOWED",
        )


def test_contract_metadata_is_derived_not_stored():
    assert get_contract_metadata(ContractType.YTB).platform_family == "YouTube"
    assert get_contract_metadata(ContractType.YTB).content_family == "long_livestream"
    assert get_contract_metadata(ContractType.YTB_SHORTS).content_family == "shorts"
    assert get_contract_metadata(ContractType.MAY_TT).platform_family == "TikTok"
