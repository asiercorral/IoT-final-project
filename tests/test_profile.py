"""Tests for plantpulse.profile. They run on a laptop, no Pi needed."""

import copy
import json

import pytest

from plantpulse import config
from plantpulse.profile import ProfileError, load_profile, validate


@pytest.mark.parametrize("name", ["basil", "basil_demo", "tomato"])
def test_shipped_profiles_load(name):
    profile = load_profile(name)
    assert profile["rain_exposed"] is False  # the school plant is sheltered


def test_default_profile_comes_from_config():
    assert load_profile()["name"] == load_profile(config.PLANT_PROFILE)["name"]


@pytest.fixture
def good():
    return copy.deepcopy(load_profile("basil"))


def test_soil_thresholds_must_rise(good):
    good["soil"]["dry_below_pct"] = 10  # below critical
    with pytest.raises(ProfileError, match="soil"):
        validate(good)


def test_rain_exposed_must_be_bool(good):
    good["rain_exposed"] = "no"
    with pytest.raises(ProfileError, match="rain_exposed"):
        validate(good)


def test_missing_value_is_rejected(good):
    del good["light"]["low_below_pct"]
    with pytest.raises(ProfileError, match="low_below_pct"):
        validate(good)


def test_missing_file(tmp_path):
    with pytest.raises(ProfileError, match="not found"):
        load_profile("cactus", plants_dir=tmp_path)


def test_broken_json(tmp_path):
    (tmp_path / "bad.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ProfileError, match="not valid JSON"):
        load_profile("bad", plants_dir=tmp_path)


def test_saturated_must_not_be_below_wet(good):
    good["soil"]["saturated_above_pct"] = 80  # below wet_above_pct
    with pytest.raises(ProfileError, match="saturated_above"):
        validate(good)


def test_wet_durations_must_be_positive_and_ordered(good):
    good["soil"]["wet_check_h"] = 72  # longer than saturated_h
    with pytest.raises(ProfileError, match="wet_check_h"):
        validate(good)


def test_cold_must_be_below_hot(good):
    good["air"]["cold_below_c"] = 40
    with pytest.raises(ProfileError, match="cold_below_c"):
        validate(good)


def test_severe_cold_must_be_below_cold(good):
    good["air"]["severe_cold_below_c"] = 15
    with pytest.raises(ProfileError, match="severe_cold_below_c"):
        validate(good)


def test_air_duration_must_be_positive(good):
    good["air"]["duration_h"] = 0
    with pytest.raises(ProfileError, match="duration_h"):
        validate(good)
