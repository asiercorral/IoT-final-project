"""Tests for the state payload, the LED bar driver and the LED program.

They run on a laptop: a fake GPIO records the pins and the test decodes the
frames the MY9221 chip would receive.
"""

import json

import pytest

from plantpulse import led_bar, led_service, state, status

START = 1_731_400_000


# --- fake hardware ------------------------------------------------------------


class Wire:
    """Records every write to the two pins of the bar, in order."""

    def __init__(self):
        self.events = []  # (pin, value)


class FakeGPIO:
    OUT = "out"
    wire = None

    def __init__(self, pin, direction):
        assert direction == FakeGPIO.OUT
        self.pin = pin

    def write(self, value):
        FakeGPIO.wire.events.append((self.pin, int(value)))


@pytest.fixture
def wire():
    FakeGPIO.wire = Wire()
    return FakeGPIO.wire


def make_bar(pin=16):
    return led_bar.LedBar(pin, gpio_class=FakeGPIO, sleep=lambda s: None)


def decode_frames(events, data_pin=16, clock_pin=17):
    """What the chip latches: bits are read on every clock edge, 208 per frame,
    and four data pulses with the clock still latch the frame."""
    frames, bits = [], []
    data = clock = 0
    pulses = 0
    for pin, value in events:
        if pin == clock_pin:
            if value != clock:
                bits.append(data)
                pulses = 0
            clock = value
        elif pin == data_pin:
            if data == 0 and value == 1:
                pulses += 1
            data = value
            if pulses == 4 and value == 0:
                frames.append(bits)
                bits, pulses = [], 0
    words = []
    for frame in frames:
        assert len(frame) == 16 * 13, f"frame has {len(frame)} bits"
        words.append([int("".join(map(str, frame[i:i + 16])), 2) for i in range(0, len(frame), 16)])
    return words


def lit(frame):
    """Segments lit in one decoded frame, as booleans."""
    assert frame[0] == led_bar.COMMAND
    assert frame[11:] == [0, 0]
    assert all(word in (led_bar.ON, led_bar.OFF) for word in frame[1:11])
    return [word == led_bar.ON for word in frame[1:11]]


# --- LED bar driver -----------------------------------------------------------


def test_clock_is_on_the_next_pin(wire):
    make_bar(pin=16).off()

    assert {pin for pin, _ in wire.events} == {16, 17}


@pytest.mark.parametrize("count", range(11))
def test_level_lights_the_first_n_segments(wire, count):
    bar = make_bar()
    wire.events.clear()

    bar.level(count)

    [frame] = decode_frames(wire.events)
    assert lit(frame) == [i < count for i in range(10)]


def test_level_is_clamped(wire):
    bar = make_bar()
    wire.events.clear()

    bar.level(15)
    bar.level(-3)

    frames = decode_frames(wire.events)
    assert lit(frames[0]) == [True] * 10
    assert lit(frames[1]) == [False] * 10


def test_any_set_of_segments_can_be_lit(wire):
    bar = make_bar()
    wire.events.clear()
    pattern = [True, False] * 5

    bar.show(pattern)

    assert lit(decode_frames(wire.events)[0]) == pattern


def test_consecutive_frames_decode_correctly(wire):
    # The clock keeps toggling from where the last frame left it.
    bar = make_bar()
    wire.events.clear()

    for count in (2, 5, 10, 0):
        bar.level(count)

    assert [sum(lit(f)) for f in decode_frames(wire.events)] == [2, 5, 10, 0]


def test_wrong_number_of_segments_is_rejected(wire):
    with pytest.raises(ValueError):
        make_bar().show([True] * 9)


# --- state payload ------------------------------------------------------------


def test_state_payload_format():
    payload = state.build_state(
        "CHECK", "Soil is dry", timestamp=START + 0.6, device_id="plant-x"
    )

    assert payload == {
        "device_id": "plant-x",
        "timestamp": START,
        "state": "CHECK",
        "status_code": "CHECK",
        "reason": "Soil is dry",
        "forecast": None,
    }


def test_unknown_state_is_rejected():
    with pytest.raises(ValueError):
        state.build_state("DRY", "Soil is dry")


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"state": "ATTENTION"}, "ATTENTION"),
        ({"state": "check"}, "CHECK"),
        ({"state": "NORMAL", "status_code": "CHECK_MOISTURE"}, "NORMAL"),
        ({"status_code": "OK"}, "NORMAL"),
        ({"status_code": "CHECK_MOISTURE"}, "CHECK"),
        ({"status_code": "ATTENTION_DRY"}, "ATTENTION"),
        ({"status_code": "FAULT_SOIL_SENSOR"}, "FAULT"),
        ({"state": "PURPLE"}, None),
        ({"status_code": 3}, None),
        ({}, None),
        (["NORMAL"], None),
        (None, None),
    ],
)
def test_state_of_a_received_message(payload, expected):
    assert state.state_of(payload) == expected


class FakeClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, json.loads(payload), qos, retain))


def test_state_is_published_retained_on_the_state_topic():
    client = FakeClient()
    payload = state.build_state("NORMAL", "fine", timestamp=START)

    state.publish_state(client, payload)

    assert client.published == [("plantpulse/school01/plant01/state", payload, 1, True)]


# --- LED program --------------------------------------------------------------


class FakeBar:
    def __init__(self):
        self.levels = []

    def level(self, count):
        self.levels.append(count)


def message(**fields):
    return json.dumps(fields).encode()


@pytest.mark.parametrize(
    "name, segments", [("NORMAL", 2), ("CHECK", 5), ("ATTENTION", 10)]
)
def test_each_state_has_its_pattern(name, segments):
    bar = FakeBar()

    led_service.LedService(bar).on_message(message(state=name))

    assert bar.levels == [segments]


def test_the_three_patterns_are_different():
    assert len(set(led_service.PATTERNS.values())) == 3


def test_the_bar_changes_on_the_first_message_of_a_new_state():
    bar = FakeBar()
    service = led_service.LedService(bar)

    for name in ("NORMAL", "CHECK", "ATTENTION", "NORMAL"):
        service.on_message(message(state=name, reason="r"))

    assert bar.levels == [2, 5, 10, 2]
    assert service.current == "NORMAL"


@pytest.mark.parametrize(
    "raw",
    [
        message(state="FAULT"),
        message(state="PURPLE"),
        message(reason="no state"),
        b"not json",
        b"\xff\xfe",
        b"",
    ],
)
def test_fault_or_unreadable_message_turns_the_bar_off_never_normal(raw):
    bar = FakeBar()
    service = led_service.LedService(bar)
    service.on_message(message(state="NORMAL"))

    service.on_message(raw)

    assert bar.levels == [2, 0]


def test_a_rule_engine_message_with_only_a_status_code_works():
    bar = FakeBar()

    led_service.LedService(bar).on_message(message(status_code="CHECK_MOISTURE"))

    assert bar.levels == [5]


def test_published_payload_drives_the_real_driver(wire):
    # State message -> LED program -> MY9221 frame, end to end without hardware.
    bar = make_bar()
    wire.events.clear()
    raw = json.dumps(state.build_state("CHECK", "dry", timestamp=START)).encode()

    led_service.LedService(bar).on_message(raw)

    assert lit(decode_frames(wire.events)[0]) == [True] * 5 + [False] * 5


def test_demo_cycles_the_three_patterns():
    bar = FakeBar()
    sleeps = []

    led_service.run_demo(led_service.LedService(bar), 3, cycles=2, sleep=sleeps.append)

    assert bar.levels == [2, 5, 10, 2, 5, 10]
    assert sleeps == [3] * 6


def test_without_grove_libraries_the_program_stops_with_a_message(monkeypatch, capsys):
    def missing(pin):
        raise ModuleNotFoundError("No module named 'grove'")

    monkeypatch.setattr(led_service, "LedBar", missing)

    with pytest.raises(SystemExit) as exc:
        led_service.main(["--demo"])

    assert exc.value.code == 1
    assert "Run this on the Pi" in capsys.readouterr().err


# --- basic soil status (T-16) feeding the state -------------------------------


@pytest.mark.parametrize(
    "pct, expected",
    [(None, "FAULT"), (0.0, "ATTENTION"), (14.9, "ATTENTION"), (15.0, "CHECK"),
     (29.9, "CHECK"), (30.0, "NORMAL"), (100.0, "NORMAL")],
)
def test_basic_status_thresholds(pct, expected):
    assert status.basic_status(pct) == expected


@pytest.mark.parametrize("pct", [None, 5.0, 20.0, 60.0])
def test_basic_status_gives_a_valid_state_message(pct):
    payload = state.build_state(status.basic_status(pct), status.basic_reason(pct))

    assert state.state_of(payload) == status.basic_status(pct)
    assert payload["reason"]
