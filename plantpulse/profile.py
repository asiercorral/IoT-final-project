"""T-23: plant profile with care thresholds and the rain-exposure flag.

Each plant has one JSON file in ``config/plants/``. The rule engine reads its
thresholds from here instead of using numbers in the code, so changing the
plant or adjusting a value after calibration needs no code change.

Show the active profile on the Pi or a laptop:

    python -m plantpulse.profile            # profile chosen in .env
    python -m plantpulse.profile tomato     # a specific profile
"""

from __future__ import annotations

import json
import sys

from plantpulse import config

REQUIRED = {
    "soil": (
        "critical_below_pct",
        "dry_below_pct",
        "wet_above_pct",
        "wet_check_h",
        "saturated_above_pct",
        "saturated_h",
    ),
    "light": ("low_below_pct", "afternoon_from_h", "afternoon_to_h", "low_afternoons"),
    "air": ("cold_below_c", "hot_above_c"),
    "rain": ("min_mm", "window_h"),
}


class ProfileError(ValueError):
    """The profile file is missing or its values do not make sense."""


def _number(profile, section, key, name):
    value = profile.get(section, {}).get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{name}: {section}.{key} must be a number, not {value!r}")
    return value


def validate(profile, name="profile"):
    """Check that every value exists and is plausible; return the profile."""
    if not isinstance(profile.get("rain_exposed"), bool):
        raise ProfileError(f"{name}: rain_exposed must be true or false")

    for section, keys in REQUIRED.items():
        for key in keys:
            _number(profile, section, key, name)

    soil = profile["soil"]
    if not (
        0
        <= soil["critical_below_pct"]
        < soil["dry_below_pct"]
        < soil["wet_above_pct"]
        <= soil["saturated_above_pct"]
        <= 100
    ):
        raise ProfileError(
            f"{name}: soil needs 0 <= critical_below < dry_below < wet_above"
            " <= saturated_above <= 100"
        )
    if not 0 < soil["wet_check_h"] <= soil["saturated_h"]:
        raise ProfileError(f"{name}: soil needs 0 < wet_check_h <= saturated_h")

    light = profile["light"]
    if not 0 <= light["low_below_pct"] <= 100:
        raise ProfileError(f"{name}: light.low_below_pct must be between 0 and 100")
    if not 0 <= light["afternoon_from_h"] < light["afternoon_to_h"] <= 24:
        raise ProfileError(f"{name}: light afternoon_from_h must be before afternoon_to_h")
    if light["low_afternoons"] < 1:
        raise ProfileError(f"{name}: light.low_afternoons must be at least 1")

    air = profile["air"]
    if not air["cold_below_c"] < air["hot_above_c"]:
        raise ProfileError(f"{name}: air.cold_below_c must be below air.hot_above_c")

    rain = profile["rain"]
    if rain["min_mm"] < 0 or rain["window_h"] <= 0:
        raise ProfileError(f"{name}: rain.min_mm must be >= 0 and rain.window_h > 0")

    return profile


def load_profile(name=None, plants_dir=None):
    """Load and validate ``config/plants/<name>.json``.

    Without a name, the plant chosen by PLANTPULSE_PLANT (default: basil) is used.
    """
    name = name or config.PLANT_PROFILE
    plants_dir = plants_dir or config.PLANTS_DIR
    path = plants_dir / f"{name}.json"
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(f"plant profile {path} not found") from None
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{path.name} is not valid JSON: {exc}") from None
    return validate(profile, path.name)


if __name__ == "__main__":
    chosen = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        print(json.dumps(load_profile(chosen), indent=2, ensure_ascii=False))
    except ProfileError as exc:
        raise SystemExit(f"Error: {exc}")
