"""T-16: basic soil status in the terminal (NORMAL / CHECK / ATTENTION).
T-25: with --publish, the status is also published to MQTT for the LED bar.

Run on the Raspberry Pi from the repository root, with the Grove venv active:
    python3 -m plantpulse.status              # print only
    python3 -m plantpulse.status --publish    # print and publish to MQTT

Calibration values are read from .env (see .env.example) or from the
command line, e.g.:
    SOIL_DRY=2850 SOIL_WET=1350 python3 -m plantpulse.status

The rule engine (T-24) will take over publishing the state; until then this
gives the LED bar a real state from the soil probe.
"""
import argparse
import os
import statistics
import time

try:                                # read SOIL_DRY / SOIL_WET from .env if available
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from plantpulse import config, state 
SOIL_CH = int(os.getenv("SOIL_CH", "0"))        # Grove port A0
SOIL_DRY = int(os.getenv("SOIL_DRY", "147"))   # raw value in dry substrate
SOIL_WET = int(os.getenv("SOIL_WET", "2461"))   # raw value in wet substrate

from plantpulse.profile import load_profile

# Thresholds come from the plant profile (T-23), chosen with PLANTPULSE_PLANT
PROFILE = load_profile()
ATTENTION_BELOW = PROFILE["soil"]["critical_below_pct"]
CHECK_BELOW = PROFILE["soil"]["dry_below_pct"]

INTERVAL_S = int(os.getenv("INTERVAL_S", "5"))  # seconds between readings

_adc = None


def soil_raw():
    """Median of 5 reads to reduce noise. None if the probe seems unplugged."""
    global _adc
    if _adc is None:                 # opened on first use, so tests need no Grove library
        from grove.adc import ADC
        _adc = ADC()
    raw = statistics.median(_adc.read_raw(SOIL_CH) for _ in range(5))
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


def basic_reason(pct):
    """One short sentence explaining ``basic_status(pct)``."""
    if pct is None:
        return "The soil probe gives no reading"
    if pct < ATTENTION_BELOW:
        return f"Soil moisture index {pct} % is below {ATTENTION_BELOW} %"
    if pct < CHECK_BELOW:
        return f"Soil moisture index {pct} % is below {CHECK_BELOW} %"
    return f"Soil moisture index {pct} % is fine"


def _connect(host, port):
    """MQTT client for --publish; reconnects by itself if the broker restarts."""
    client = state.make_client(f"{config.DEVICE_ID}-status")
    client.connect(host, port)
    client.loop_start()
    return client


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python3 -m plantpulse.status")
    parser.add_argument("--publish", action="store_true",
                        help=f"also publish the status to {config.TOPIC_STATE}")
    parser.add_argument("--host", default=config.MQTT_HOST)
    parser.add_argument("--port", type=int, default=config.MQTT_PORT)
    args = parser.parse_args()

    if SOIL_DRY == SOIL_WET:
        raise SystemExit("SOIL_DRY and SOIL_WET must be different: check your .env")

    client = None
    if args.publish:
        try:
            client = _connect(args.host, args.port)
        except ImportError as exc:
            raise SystemExit(f"paho-mqtt not found ({exc}). Run: pip install -r requirements.txt")
        except OSError as exc:
            raise SystemExit(f"Cannot reach the MQTT broker at {args.host}:{args.port} ({exc})")

    print(f"Soil status every {INTERVAL_S} s (dry={SOIL_DRY}, wet={SOIL_WET}). Ctrl+C to stop.")
    try:
        while True:
            try:
                raw = soil_raw()
            except OSError:              # I2C error: treat like a missing sensor
                raw = None
            pct = soil_pct(raw) if raw is not None else None
            status = basic_status(pct)
            print(f"{time.strftime('%H:%M:%S')}  raw={raw}  soil={pct}%  -> {status}")
            if client is not None:
                state.publish_state(client, state.build_state(status, basic_reason(pct)))
            time.sleep(INTERVAL_S)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if client is not None:
            client.loop_stop()
            client.disconnect()
