from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from core.dashboard_processor import DashboardProcessor, DashboardResult
from core.file_processor import UploadedExcel
from database.dashboard_repository import DashboardRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DASHBOARD_SOURCE_DIR = PROJECT_ROOT / "data" / "input" / "dashboard"


@dataclass(frozen=True)
class DashboardBootstrapResult:
    """Describes whether a fresh local database was populated from source files."""

    attempted: bool
    source_files: tuple[Path, ...]
    imported_result: DashboardResult | None
    saved_count: int
    total_count: int


def _source_files(source_dir: Path) -> tuple[Path, ...]:
    if not source_dir.exists():
        return ()
    return tuple(
        sorted(
            (
                path
                for path in source_dir.glob("*.xlsx")
                if path.is_file() and not path.name.startswith("~$")
            ),
            key=lambda path: path.name.casefold(),
        )
    )


def ensure_dashboard_seeded(
    database_path: Path | str,
    timezone: str,
    *,
    source_dir: Path = DEFAULT_DASHBOARD_SOURCE_DIR,
) -> DashboardBootstrapResult:
    """Populate an empty dashboard from the project-local source files.

    The seed files travel with the local deployment.  As a result, a new or
    reset SQLite database can reopen the dashboard without asking the user to
    upload the same monthly exports again.
    """
    repository = DashboardRepository(database_path)
    existing_count = repository.count_posts()
    files = _source_files(source_dir)
    if existing_count or not files:
        return DashboardBootstrapResult(
            attempted=False,
            source_files=files,
            imported_result=None,
            saved_count=0,
            total_count=existing_count,
        )

    uploads = [
        UploadedExcel(name=file.name, content=file.read_bytes()) for file in files
    ]
    imported_result = DashboardProcessor(database_path, timezone).process(uploads)
    saved = repository.save_monthly_import(
        imported_result.data,
        replace_months=True,
        source_files=[file.name for file in files],
        file_hashes={
            file.name: hashlib.sha256(file.read_bytes()).hexdigest()
            for file in files
        },
        file_reports=imported_result.file_reports,
    )
    return DashboardBootstrapResult(
        attempted=True,
        source_files=files,
        imported_result=imported_result,
        saved_count=saved.saved_count,
        total_count=saved.total_count,
    )
