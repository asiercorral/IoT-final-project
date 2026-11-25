"""The plant state: payload format and MQTT publishing.

Whoever decides the state (today the basic soil status in ``status.py``,
later the rule engine) publishes it here, retained, on ``TOPIC_STATE``. The
LED program and the web page read it from there; a retained message means a
program that starts later still gets the current state at once.

Payload, one JSON object:

    {
      "device_id": "plantpulse-school01-plant01",
      "timestamp": 1728920000,
      "state": "CHECK",
      "status_code": "CHECK_DRY",
      "reason": "Soil is getting dry (38 %). Feel the soil and water if it is dry below the surface.",
      "forecast": null
    }

``state`` is one of ``STATES`` and is what the LED bar shows. ``status_code``
can be more specific (for example ``CHECK_MOISTURE``) and defaults to the
state. ``forecast`` is the forecast the decision used, or null.

Publish a state by hand, for example to try the LED bar without sensors:

    python -m plantpulse.state CHECK --reason "testing the bar"
"""

from __future__ import annotations

import argparse
import json
import time

from plantpulse import config

STATES = ("NORMAL", "CHECK", "ATTENTION", "FAULT")


def build_state(
    state,
    reason,
    status_code=None,
    forecast=None,
    timestamp=None,
    device_id=config.DEVICE_ID,
):
    """One state message in the payload format above."""
    if state not in STATES:
        raise ValueError(f"state must be one of {', '.join(STATES)}, not {state!r}")
    return {
        "device_id": device_id,
        "timestamp": int(time.time() if timestamp is None else timestamp),
        "state": state,
        "status_code": status_code or state,
        "reason": reason,
        "forecast": forecast,
    }


def state_of(payload):
    """The state (one of ``STATES``) in a received message, or None if it has none.

    Reads ``state`` first. A message with only a ``status_code`` such as
    ``OK`` or ``CHECK_MOISTURE`` is understood by its prefix, so the LED
    keeps working whichever of the two fields the rule engine fills in.
    """
    if not isinstance(payload, dict):
        return None
    state = payload.get("state")
    if isinstance(state, str) and state.upper() in STATES:
        return state.upper()
    code = payload.get("status_code")
    if not isinstance(code, str):
        return None
    code = code.upper()
    if code in ("OK", "NORMAL"):
        return "NORMAL"
    for state in STATES:
        if code.startswith(state):
            return state
    return None


def make_client(client_id):
    """A paho-mqtt client. Imported here so the rest of the module needs no paho."""
    import paho.mqtt.client as mqtt

    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)


def publish_state(client, payload, topic=config.TOPIC_STATE):
    """Publish one state message, retained, with QoS 1."""
    return client.publish(topic, json.dumps(payload), qos=1, retain=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m plantpulse.state",
        description="Publish one plant state to MQTT (retained), for example to try the LED bar.",
    )
    parser.add_argument("state", type=str.upper, choices=STATES)
    parser.add_argument("--reason", default="published by hand", help="reason text")
    parser.add_argument("--status-code", help="specific code (default: the state)")
    parser.add_argument("--host", default=config.MQTT_HOST, help="broker (default: %(default)s)")
    parser.add_argument("--port", type=int, default=config.MQTT_PORT, help="(default: %(default)s)")
    args = parser.parse_args(argv)

    payload = build_state(args.state, args.reason, status_code=args.status_code)
    try:
        client = make_client(f"{config.DEVICE_ID}-state-cli")
    except ImportError as exc:
        parser.exit(1, f"paho-mqtt not found ({exc}). Run: pip install -r requirements.txt\n")
    try:
        client.connect(args.host, args.port)
    except OSError as exc:
        parser.exit(1, f"Cannot reach the MQTT broker at {args.host}:{args.port} ({exc}).\n")
    client.loop_start()
    try:
        publish_state(client, payload).wait_for_publish(timeout=5)
    finally:
        client.loop_stop()
        client.disconnect()
    print(f"{config.TOPIC_STATE} <- {json.dumps(payload)}")


if __name__ == "__main__":
    main()
