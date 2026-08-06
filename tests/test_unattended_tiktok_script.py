from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_unattended_script_runs_without_streamlit(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    process = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "update_tiktok_followers.py"),
            "--database-path",
            str(tmp_path / "koc.db"),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0
    summary = json.loads(process.stdout.strip().splitlines()[-1])
    assert summary == {
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "stopped": False,
        "stop_error_code": None,
    }
