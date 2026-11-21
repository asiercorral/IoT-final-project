"""State display program: show the plant state on the Grove 16x2 LCD.

(The backlog calls this the "LED program"; the hardware is the Grove 16x2
LCD, White on Blue, on an I2C port.)

It subscribes to the retained state topic and rewrites the screen as soon
as a new state arrives, so the screen follows the state within the same
reading cycle. The screens are the ones on the printed legend card
(docs/led-legend.pdf): a short message on the first row and a 10-cell bar
on the second.

    NORMAL     All good           2 cells
    CHECK      Check the plant    5 cells
    ATTENTION  Plant needs help   10 cells

A FAULT says "Sensor problem". An unreadable message or one without a
state says "No plant state", so missing data is never shown as All good.

Run on the Pi:

    python -m plantpulse.led_service           # follow the state over MQTT
    python -m plantpulse.led_service --demo    # cycle the three screens, no MQTT
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import signal
import time

from plantpulse import config, lcd, state

log = logging.getLogger(__name__)

# Bar cells lit for each state, out of BAR_CELLS.
BAR_CELLS = 10
PATTERNS = {
    "NORMAL": 2,
    "CHECK": 5,
    "ATTENTION": 10,
}
HEADINGS = {
    "NORMAL": "All good",
    "CHECK": "Check the plant",
    "ATTENTION": "Plant needs help",
}
FAULT_SCREEN = ("Sensor problem", "Tell the teacher")
UNKNOWN_SCREEN = ("No plant state", "Tell the teacher")
STARTING_SCREEN = ("PlantPulse", "Starting...")


def screen_for(name):
    """The two rows shown for one state (one of ``state.STATES`` or None)."""
    if name in PATTERNS:
        return HEADINGS[name], lcd.bar(PATTERNS[name], BAR_CELLS)
    if name == "FAULT":
        return FAULT_SCREEN
    return UNKNOWN_SCREEN


class LedService:
    """Turns state messages into screens."""

    def __init__(self, display):
        self.display = display
        self.current = None

    def show(self, new_state):
        """Show one state (one of ``state.STATES``, or None when unknown)."""
        # The screen is rewritten even when the state has not changed, so a
        # screen that was unplugged or glitched is put right by the next message.
        try:
            self.display.show(*screen_for(new_state))
        except OSError as exc:
            log.warning("LCD does not answer (%s); trying again with the next state", exc)
        if new_state != self.current:
            log.info("screen: %s -> %s", self.current or "none", new_state or "unknown")
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
        log.warning("lost the broker (%s); the screen keeps the last state", reason_code)

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
        description="Show the PlantPulse state on the Grove 16x2 LCD.",
    )
    parser.add_argument("--demo", action="store_true",
                        help="cycle the three screens without MQTT")
    parser.add_argument("--seconds", type=float, default=3,
                        help="seconds per screen in --demo (default: %(default)s)")
    parser.add_argument("--host", default=config.MQTT_HOST, help="broker (default: %(default)s)")
    parser.add_argument("--port", type=int, default=config.MQTT_PORT, help="(default: %(default)s)")
    parser.add_argument("--address", type=lambda v: int(v, 0), default=config.LCD_I2C_ADDRESS,
                        help="I2C address of the LCD (default: 0x%(default)X)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)

    try:
        display = lcd.Lcd(args.address)
    except ImportError as exc:
        parser.exit(1, f"Grove libraries not found ({exc}). Run this on the Pi.\n")

    service = LedService(display)
    try:
        display.show(*STARTING_SCREEN)
    except OSError as exc:
        log.warning("LCD does not answer at 0x%X (%s): is it on an I2C port?", args.address, exc)
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
        try:
            display.show("PlantPulse", "Stopped")
        except OSError:
            pass


if __name__ == "__main__":
    main()
