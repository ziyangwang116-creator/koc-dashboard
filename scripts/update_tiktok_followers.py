from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings  # noqa: E402
from database.koc_repository import KOCRepository  # noqa: E402
from services.follower_service import FollowerService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="使用本地登录的持久化浏览器，串行更新 TT 达人粉丝数。"
    )
    parser.add_argument("--database-path", type=Path)
    args = parser.parse_args()
    settings = load_settings()
    repository = KOCRepository(args.database_path or settings.database_path)
    service = FollowerService(
        repository,
        youtube_api_key=settings.youtube_api_key,
        tiktok_browser_data_dir=settings.tiktok_browser_data_dir,
        tiktok_persistent_headless=settings.tiktok_persistent_headless,
    )

    def show_progress(completed: int, total: int, _record: object, _outcome: object) -> None:
        print(f"PROGRESS {completed}/{total}")

    result = service.update_all_tiktok(progress_callback=show_progress)
    summary = {
        "success": result.tiktok_success_count,
        "failed": result.tiktok_failed_count,
        "skipped": result.skipped_count,
        "stopped": result.stopped,
        "stop_error_code": result.stop_error_code,
    }
    print(json.dumps(summary, ensure_ascii=False))
    if result.stop_error_code in {
        "CAPTCHA_REQUIRED",
        "SECURITY_VERIFICATION_REQUIRED",
        "ACCESS_RESTRICTED",
        "TIKTOK_LOGIN_REQUIRED",
        "TIKTOK_BROWSER_TIMEOUT",
    }:
        return 2
    return 1 if result.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
