from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from core.koc_mapper import KOCMapper
from core.transformer import TransformResult, transform_data


@dataclass(frozen=True)
class DataPipeline:
    """The single transformation entry point used by one or many files."""

    mapper: KOCMapper
    timezone: str

    def process(
        self,
        raw_data: pd.DataFrame,
        *,
        column_mapping: Mapping[str, str] | None = None,
    ) -> TransformResult:
        return transform_data(
            raw_data,
            mapper=self.mapper,
            timezone=self.timezone,
            column_mapping=column_mapping,
        )
