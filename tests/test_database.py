import sqlite3

import pytest

from database.db import DEFAULT_KOCS, connect, get_koc_mapping


def test_database_is_initialized_with_fixed_kocs(tmp_path):
    mapping = get_koc_mapping(tmp_path / "koc.db")

    assert len(mapping) == len(DEFAULT_KOCS)
    assert len(mapping) == 63
    assert mapping["107258"] == "ゆい／のん"
    assert mapping["16001100"] == "なみかりちゃんねる"
    assert mapping["23592591"] == "シアン🧻"


def test_managed_connection_closes_after_context(tmp_path):
    with connect(tmp_path / "connection.db") as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
