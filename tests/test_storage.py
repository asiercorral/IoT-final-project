"""Tests for plantpulse.storage. They use a temporary database file."""

import sqlite3
from contextlib import closing

import pytest

from plantpulse import acquisition, storage


def columns(path):
    with closing(sqlite3.connect(path)) as conn:
        return [row[1] for row in conn.execute("PRAGMA table_info(readings)")]


def insert(path, device_id, timestamp, light_pct=None):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT INTO readings (device_id, timestamp, light_pct) VALUES (?, ?, ?)",
            (device_id, timestamp, light_pct),
        )
        conn.commit()


def test_init_creates_the_folder_and_the_table(tmp_path):
    path = tmp_path / "data" / "plantpulse.db"

    storage.init_db(path)

    assert path.is_file()
    assert storage.count_readings(path) == 0


def test_columns_match_the_telemetry_payload(tmp_path):
    path = tmp_path / "plantpulse.db"

    storage.init_db(path)

    assert columns(path) == ["device_id", "timestamp", *acquisition.SENSOR_KEYS]


def test_running_init_again_keeps_the_readings(tmp_path):
    path = tmp_path / "plantpulse.db"
    storage.init_db(path)
    insert(path, "plant-x", 1_731_400_000, light_pct=70.2)

    storage.init_db(path)

    assert storage.count_readings(path) == 1


def test_the_same_reading_cannot_be_stored_twice(tmp_path):
    path = tmp_path / "plantpulse.db"
    storage.init_db(path)
    insert(path, "plant-x", 1_731_400_000)

    with pytest.raises(sqlite3.IntegrityError):
        insert(path, "plant-x", 1_731_400_000)


def test_a_missing_value_is_null(tmp_path):
    path = tmp_path / "plantpulse.db"
    storage.init_db(path)
    insert(path, "plant-x", 1_731_400_000)

    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("SELECT temperature_c, light_pct FROM readings").fetchone()

    assert row == (None, None)


def test_command_line_creates_the_database(tmp_path, capsys):
    path = tmp_path / "plantpulse.db"

    storage.main(["--db", str(path)])

    assert path.is_file()
    assert "0 readings" in capsys.readouterr().out
