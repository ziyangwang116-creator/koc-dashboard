import pytest

from database.koc_repository import KOCRepository, KOCRepositoryError
from followers.url_parser import identify_platform


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/@handle",
        "https://www.youtube.com/channel/UC123",
        "https://m.youtube.com/user/name",
    ],
)
def test_valid_youtube_homepage_can_be_saved(tmp_path, url):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(user_id=url, koc_name="达人", homepage_url=url)
    assert record.homepage_url == url
    assert identify_platform(url) == "YouTube"


@pytest.mark.parametrize(
    "url",
    ["https://tiktok.com/@name", "https://www.tiktok.com/@name", "https://m.tiktok.com/@name"],
)
def test_valid_tiktok_homepage_can_be_saved(tmp_path, url):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(user_id=url, koc_name="达人", homepage_url=url)
    assert record.homepage_url == url
    assert identify_platform(url) == "TikTok"


def test_invalid_homepage_url_is_rejected(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    with pytest.raises(KOCRepositoryError, match="http"):
        repository.create(user_id="invalid-url", koc_name="达人", homepage_url="youtube.com/@x")


def test_empty_homepage_url_is_allowed(tmp_path):
    repository = KOCRepository(tmp_path / "koc.db")
    record = repository.create(user_id="empty-url", koc_name="达人", homepage_url="  ")
    assert record.homepage_url is None


def test_unknown_homepage_platform_is_not_identified():
    assert identify_platform("https://example.com/creator") is None
