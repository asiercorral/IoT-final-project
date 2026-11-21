"""LED program: show the plant state on the Grove LED Bar.

It subscribes to the retained state topic and changes the bar as soon as a
new state arrives, so the bar follows the state within the same reading
cycle. The patterns are the ones on the printed legend card
(docs/led-legend.pdf):

    NORMAL     two steady segments
    CHECK      half the bar (5 segments)
    ATTENTION  the full bar (10 segments)

A FAULT, an unreadable message or no state at all turns the bar off, so
missing data is never shown as Normal. The blinking fault pattern comes
with T-39.

Run on the Pi:

    python -m plantpulse.led_service           # follow the state over MQTT
    python -m plantpulse.led_service --demo    # cycle the three patterns, no MQTT
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import signal
import time

from plantpulse import config, state
from plantpulse.led_bar import LedBar

log = logging.getLogger(__name__)

# Segments lit for each state. Anything else (FAULT, unknown) is off.
PATTERNS = {
    "NORMAL": 2,
    "CHECK": 5,
    "ATTENTION": 10,
}


class LedService:
    """Turns state messages into bar patterns."""

    def __init__(self, bar):
        self.bar = bar
        self.current = None

    def show(self, new_state):
        """Show one state (one of ``state.STATES``, or None when unknown)."""
        # The bar is rewritten even when the state has not changed, so a
        # glitch on the wire is corrected by the next message.
        self.bar.level(PATTERNS.get(new_state, 0))
        if new_state != self.current:
            log.info("LED bar: %s -> %s", self.current or "none", new_state or "unknown (off)")
            self.current = new_state

    def on_message(self, raw):
        """Handle the bytes of one message from the state topic."""
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("state message is not JSON: %r", raw[:80])
            payload = None
        new_state = state.state_of(payload)
        if new_state is None and payload is not None:
            log.warning("state message has no known state: %s", payload)
        self.show(new_state)


def run_demo(service, seconds, cycles=None, sleep=time.sleep):
    """Show NORMAL, CHECK and ATTENTION in turn, ``seconds`` each."""
    steps = itertools.cycle(PATTERNS)
    if cycles is not None:
        steps = itertools.islice(steps, cycles * len(PATTERNS))
    for name in steps:
        service.show(name)
        sleep(seconds)


def run_mqtt(service, host, port):
    """Follow the state topic until stopped; reconnects if the broker goes away."""
    client = state.make_client(f"{config.DEVICE_ID}-led")

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("broker refused the connection: %s", reason_code)
            return
        # Subscribing again on every connect brings back the retained state
        # after the broker restarts.
        client.subscribe(config.TOPIC_STATE, qos=1)
        log.info("connected to %s:%d, following %s", host, port, config.TOPIC_STATE)

    def on_disconnect(client, userdata, flags, reason_code, properties):
        log.warning("lost the broker (%s); the bar keeps the last state", reason_code)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = lambda client, userdata, msg: service.on_message(msg.payload)
    client.connect_async(host, port)
    try:
        # Keeps trying when the broker is not up yet, as at boot.
        client.loop_forever(retry_first_connection=True)
    finally:
        client.disconnect()


def _stop(signum, frame):
    # systemd stops services with SIGTERM; end like Ctrl+C does.
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m plantpulse.led_service",
        description="Show the PlantPulse state on the Grove LED Bar.",
    )
    parser.add_argument("--demo", action="store_true",
                        help="cycle the three patterns without MQTT")
    parser.add_argument("--seconds", type=float, default=3,
                        help="seconds per pattern in --demo (default: %(default)s)")
    parser.add_argument("--host", default=config.MQTT_HOST, help="broker (default: %(default)s)")
    parser.add_argument("--port", type=int, default=config.MQTT_PORT, help="(default: %(default)s)")
    parser.add_argument("--pin", type=int, default=config.LED_BAR_PIN,
                        help="Grove port of the bar (default: D%(default)s)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)

    try:
        bar = LedBar(args.pin)
    except ImportError as exc:
        parser.exit(1, f"Grove libraries not found ({exc}). Run this on the Pi.\n")

    service = LedService(bar)
    service.show(None)  # off until the first state arrives
    try:
        if args.demo:
            run_demo(service, args.seconds)
        else:
            run_mqtt(service, args.host, args.port)
    except ImportError as exc:
        parser.exit(1, f"paho-mqtt not found ({exc}). Run: pip install -r requirements.txt\n")
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        bar.off()


if __name__ == "__main__":
    main()
