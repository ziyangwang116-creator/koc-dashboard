from datetime import date
from io import BytesIO

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from ui.data_processing import _format_metric_value


def test_metric_value_formatter_handles_all_common_report_scalars():
    assert _format_metric_value(None) is None
    assert _format_metric_value(pd.NA) is None
    assert _format_metric_value(pd.NaT) is None
    assert _format_metric_value(float("nan")) is None
    assert _format_metric_value(np.int64(12)) == "12"
    assert _format_metric_value(date(2024, 1, 2)) == "2024-01-02"


def test_uploaded_file_with_no_valid_date_renders_metrics_without_exception():
    dataframe = pd.DataFrame(
        {
            "view": [1],
            "subtype": ["short"],
            "title": ["缺少时间字段的文件"],
            "userId": [107258],
            "url": ["https://example.com/a"],
        }
    )
    output = BytesIO()
    dataframe.to_excel(output, index=False, engine="openpyxl")

    app = AppTest.from_file("app.py", default_timeout=30).run()
    app.file_uploader[0].set_value(
        [
            (
                "missing_timestamp.xlsx",
                output.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        ]
    )
    app.run()
    app.button[0].click()
    app.run()

    assert len(app.exception) == 0
    assert len(app.metric) == 14
