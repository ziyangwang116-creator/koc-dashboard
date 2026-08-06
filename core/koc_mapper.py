from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd

from core.user_id import normalize_user_id
from database.db import get_koc_mapping


@dataclass(frozen=True)
class KOCMapper:
    mapping: Mapping[str, str]

    @classmethod
    def from_database(cls, database_path: Path | str) -> "KOCMapper":
        return cls(get_koc_mapping(database_path))

    def map_series(self, user_ids: pd.Series) -> tuple[pd.Series, pd.Series]:
        normalized = user_ids.map(normalize_user_id).astype("string")
        names = normalized.map(self.mapping).astype("string")
        return names, normalized
