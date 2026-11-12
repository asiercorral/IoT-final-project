"""T-16: basic soil status in the terminal (NORMAL / CHECK / ATTENTION).

Run on the Raspberry Pi from the repository root:
    SOIL_DRY=2850 SOIL_WET=1350 python3 -m plantpulse.status
"""
import os
import statistics
import time

from grove.adc import ADC

# Calibration: raw ADC values measured in dry and wet substrate (T-12)
SOIL_CH = int(os.getenv("SOIL_CH", "0"))        # Grove port A0
SOIL_DRY = int(os.getenv("SOIL_DRY", "2900"))
SOIL_WET = int(os.getenv("SOIL_WET", "1300"))

# Provisional thresholds in % moisture index; final values in the plant profile (T-23)
ATTENTION_BELOW = 15
CHECK_BELOW = 30

INTERVAL_S = int(os.getenv("INTERVAL_S", "5"))

adc = ADC()


def soil_raw():
    """Median of 5 reads to reduce noise. None if the probe seems unplugged."""
    raw = statistics.median(adc.read_raw(SOIL_CH) for _ in range(5))
    if raw <= 5 or raw >= 4090:      # 0 or 4095: nothing connected
        return None
    return int(raw)


def soil_pct(raw):
    """Map the raw value to 0-100 % between our dry and wet references."""
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
    print(f"Soil status every {INTERVAL_S} s (dry={SOIL_DRY}, wet={SOIL_WET}). Ctrl+C to stop.")
    while True:
        try:
            raw = soil_raw()
        except OSError:              # I2C error: treat like a missing sensor
            raw = None
        pct = soil_pct(raw) if raw is not None else None
        print(f"{time.strftime('%H:%M:%S')}  raw={raw}  soil={pct}%  -> {basic_status(pct)}")
        time.sleep(INTERVAL_S)