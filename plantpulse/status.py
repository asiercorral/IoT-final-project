"""T-16: basic soil status in the terminal (NORMAL / CHECK / ATTENTION).

Run on the Raspberry Pi from the repository root, with the Grove venv active:
    python3 -m plantpulse.status

Calibration values are read from .env (see .env.example) or from the
command line, e.g.:
    SOIL_DRY=2850 SOIL_WET=1350 python3 -m plantpulse.status
"""
import os
import statistics
import time

from grove.adc import ADC

try:                                # read SOIL_DRY / SOIL_WET from .env if available
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# TODO(T-12): replace with calibrated values; set SOIL_DRY / SOIL_WET in .env
SOIL_CH = int(os.getenv("SOIL_CH", "0"))        # Grove port A0
SOIL_DRY = int(os.getenv("SOIL_DRY", "2900"))   # raw value in dry substrate
SOIL_WET = int(os.getenv("SOIL_WET", "1300"))   # raw value in wet substrate

# TODO(T-23): move thresholds to the plant profile
ATTENTION_BELOW = 15                            # % moisture index
CHECK_BELOW = 30

INTERVAL_S = int(os.getenv("INTERVAL_S", "5"))  # seconds between readings

adc = ADC()


def soil_raw():
    """Median of 5 reads to reduce noise. None if the probe seems unplugged."""
    raw = statistics.median(adc.read_raw(SOIL_CH) for _ in range(5))
    if raw <= 5 or raw >= 4090:      # 0 or 4095: nothing connected
        return None
    return int(raw)


def soil_pct(raw):
    """Map the raw value to 0-100 % between our dry and wet references.

    Works for both probe types: capacitive probes read higher when dry,
    resistive probes read higher when wet.
    """
    pct = (SOIL_DRY - raw) / (SOIL_DRY - SOIL_WET) * 100
    return round(min(max(pct, 0), 100), 1)


def basic_status(pct):
    """Turn the moisture index into a status for the pupils."""
    if pct is None:
        return "FAULT"
    if pct < ATTENTION_BELOW:
        return "ATTENTION"
    if pct < CHECK_BELOW:
        return "CHECK"
    return "NORMAL"


if __name__ == "__main__":
    if SOIL_DRY == SOIL_WET:
        raise SystemExit("SOIL_DRY and SOIL_WET must be different: check your .env")

    print(f"Soil status every {INTERVAL_S} s (dry={SOIL_DRY}, wet={SOIL_WET}). Ctrl+C to stop.")
    try:
        while True:
            try:
                raw = soil_raw()
            except OSError:              # I2C error: treat like a missing sensor
                raw = None
            pct = soil_pct(raw) if raw is not None else None
            print(f"{time.strftime('%H:%M:%S')}  raw={raw}  soil={pct}%  -> {basic_status(pct)}")
            time.sleep(INTERVAL_S)
    except KeyboardInterrupt:
        print("\nStopped.")