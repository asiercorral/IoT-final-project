"""Tests for the state payload, the LCD driver and the state display program.

They run on a laptop: a fake I2C bus plays the LCD controller and keeps
what the screen would show.
"""

import json

import pytest

from plantpulse import lcd, led_service, state, status

START = 1_731_400_000


# --- fake hardware ------------------------------------------------------------


class FakeLcdBus:
    """Plays the AIP31068 controller: follows commands and keeps the screen."""

    def __init__(self, address=0x3E):
        self.address = address
        self.rows = [bytearray(b"?" * 40), bytearray(b"?" * 40)]
        self.cgram = bytearray(64)
        self.target = None       # ("ddram", row, col) or ("cgram", index)
        self.display_on = False
        self.writes = 0
        self.unplugged = False

    def write_byte_data(self, address, control, value):
        if self.unplugged:
            raise OSError(121, "Remote I/O error")
        assert address == self.address
        self.writes += 1
        if control == lcd.COMMAND:
            self._command(value)
        elif control == lcd.DATA:
            self._data(value)
        else:
            raise AssertionError(f"unknown control byte {control:#x}")

    def _command(self, value):
        if value & 0x80:
            ddram = value & 0x7F
            self.target = ("ddram", ddram // 0x40, ddram % 0x40)
        elif value & 0x40:
            self.target = ("cgram", value & 0x3F)
        elif value == 0x01:
            self.rows = [bytearray(b" " * 40), bytearray(b" " * 40)]
            self.target = ("ddram", 0, 0)
        elif value & 0x08 and not value & 0x30:
            self.display_on = bool(value & 0x04)

    def _data(self, value):
        if self.target[0] == "cgram":
            self.cgram[self.target[1]] = value
            self.target = ("cgram", self.target[1] + 1)
        else:
            _, row, col = self.target
            self.rows[row][col] = value
            self.target = ("ddram", row, col + 1)

    def screen(self):
        """The two visible rows; bar cells as '#' (full) and '_' (empty)."""
        cells = {lcd.FULL: "#", lcd.EMPTY: "_"}
        return [
            "".join(cells.get(b, chr(b)) for b in row[: lcd.COLS]) for row in self.rows
        ]


def make_lcd(bus=None):
    return lcd.Lcd(0x3E, bus=bus or FakeLcdBus(), sleep=lambda s: None)


# --- LCD driver -----------------------------------------------------------------


def test_text_appears_on_both_rows():
    bus = FakeLcdBus()

    make_lcd(bus).show("Hello", "PlantPulse")

    assert bus.display_on
    assert bus.screen() == ["Hello" + " " * 11, "PlantPulse" + " " * 6]


def test_long_text_is_cut_to_16_characters():
    bus = FakeLcdBus()

    make_lcd(bus).show("This line is far too long", "")

    assert bus.screen()[0] == "This line is far"


def test_a_new_screen_replaces_the_old_one_completely():
    bus = FakeLcdBus()
    screen = make_lcd(bus)

    screen.show("Check the plant", lcd.bar(5))
    screen.show("All good", lcd.bar(2))

    assert bus.screen() == ["All good        ", "   ##________   "]


@pytest.mark.parametrize("lit", range(11))
def test_bar_has_ten_centred_cells(lit):
    row = lcd.bar(lit)

    assert len(row) == lcd.COLS
    assert row[:3] == row[13:] == b"   "
    assert list(row[3:13]) == [lcd.FULL] * lit + [lcd.EMPTY] * (10 - lit)


def test_bar_is_clamped():
    assert lcd.bar(15) == lcd.bar(10)
    assert lcd.bar(-2) == lcd.bar(0)


def test_empty_cell_is_a_hollow_box_in_custom_character_zero():
    bus = FakeLcdBus()

    make_lcd(bus).show("", lcd.bar(0))

    assert tuple(bus.cgram[:8]) == lcd.EMPTY_PATTERN


def test_non_ascii_text_does_not_crash():
    bus = FakeLcdBus()

    make_lcd(bus).show("Plántula", "")

    assert bus.screen()[0].startswith("Pl?ntula")


def test_setup_runs_once_then_again_after_the_screen_is_replugged():
    bus = FakeLcdBus()
    screen = make_lcd(bus)
    screen.show("one", "")
    writes_with_setup = bus.writes
    screen.show("two", "")
    assert bus.writes - writes_with_setup < writes_with_setup  # no setup the 2nd time

    bus.unplugged = True
    with pytest.raises(OSError):
        screen.show("three", "")
    replugged = FakeLcdBus()     # fresh controller: lost its settings
    screen._bus = replugged
    screen.show("four", "")

    assert replugged.display_on
    assert replugged.screen()[0].startswith("four")


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


# --- state display program ---------------------------------------------------


def message(**fields):
    return json.dumps(fields).encode()


def displayed(service, *raws):
    """Feed messages to the program; return what the screen shows at the end."""
    for raw in raws:
        service.on_message(raw)
    return service.display._bus.screen()


def make_service():
    return led_service.LedService(make_lcd())


@pytest.mark.parametrize(
    "name, screen",
    [
        ("NORMAL", ["All good        ", "   ##________   "]),
        ("CHECK", ["Check the plant ", "   #####_____   "]),
        ("ATTENTION", ["Plant needs help", "   ##########   "]),
    ],
)
def test_each_state_has_its_screen(name, screen):
    assert displayed(make_service(), message(state=name)) == screen


def test_the_three_patterns_are_different():
    assert len(set(led_service.PATTERNS.values())) == 3
    assert len(set(led_service.HEADINGS.values())) == 3


def test_the_screen_changes_on_the_first_message_of_a_new_state():
    service = make_service()
    bars = []

    for name in ("NORMAL", "CHECK", "ATTENTION", "NORMAL"):
        bars.append(displayed(service, message(state=name, reason="r"))[1].count("#"))

    assert bars == [2, 5, 10, 2]
    assert service.current == "NORMAL"


def test_fault_says_sensor_problem():
    screen = displayed(make_service(), message(state="NORMAL"), message(state="FAULT"))

    assert screen == ["Sensor problem  ", "Tell the teacher"]


@pytest.mark.parametrize(
    "raw",
    [message(state="PURPLE"), message(reason="no state"), b"not json", b"\xff\xfe", b""],
)
def test_unreadable_message_is_never_shown_as_all_good(raw):
    screen = displayed(make_service(), message(state="NORMAL"), raw)

    assert screen == ["No plant state  ", "Tell the teacher"]


def test_a_rule_engine_message_with_only_a_status_code_works():
    screen = displayed(make_service(), message(status_code="CHECK_MOISTURE"))

    assert screen[0].startswith("Check the plant")


def test_published_payload_reaches_the_screen():
    # build_state -> JSON -> program -> I2C writes, end to end without hardware.
    raw = json.dumps(state.build_state("ATTENTION", "dry", timestamp=START)).encode()

    assert displayed(make_service(), raw)[0] == "Plant needs help"


def test_an_unplugged_screen_does_not_stop_the_program():
    service = make_service()
    service.display._bus.unplugged = True

    service.on_message(message(state="CHECK"))   # logged, not raised

    service.display._bus.unplugged = False
    assert displayed(service, message(state="NORMAL"))[0].startswith("All good")


def test_demo_cycles_the_three_screens():
    shown = []

    class Recorder:
        def show(self, line1, line2):
            shown.append(line1)

    sleeps = []
    led_service.run_demo(led_service.LedService(Recorder()), 3, cycles=2, sleep=sleeps.append)

    assert shown == ["All good", "Check the plant", "Plant needs help"] * 2
    assert sleeps == [3] * 6


def test_every_screen_fits_in_16_columns():
    for name in (*state.STATES, None):
        assert all(len(lcd.to_row(row)) == lcd.COLS for row in led_service.screen_for(name))
        assert all(len(row) <= lcd.COLS for row in led_service.screen_for(name))


def test_without_grove_libraries_the_program_stops_with_a_message(monkeypatch, capsys):
    def missing(address):
        raise ModuleNotFoundError("No module named 'grove'")

    monkeypatch.setattr(lcd, "Lcd", missing)

    with pytest.raises(SystemExit) as exc:
        led_service.main(["--demo"])

    assert exc.value.code == 1
    assert "Run this on the Pi" in capsys.readouterr().err


# --- basic soil status (T-16) feeding the state -------------------------------


def test_basic_status_thresholds():
    # Thresholds come from the plant profile (T-23), so test against them
    attention, check = status.ATTENTION_BELOW, status.CHECK_BELOW
    assert status.basic_status(None) == "FAULT"
    assert status.basic_status(0.0) == "ATTENTION"
    assert status.basic_status(attention - 0.1) == "ATTENTION"
    assert status.basic_status(attention) == "CHECK"
    assert status.basic_status(check - 0.1) == "CHECK"
    assert status.basic_status(check) == "NORMAL"
    assert status.basic_status(100.0) == "NORMAL"

@pytest.mark.parametrize("pct", [None, 5.0, 20.0, 60.0])
def test_basic_status_gives_a_valid_state_message(pct):
    payload = state.build_state(status.basic_status(pct), status.basic_reason(pct))

    assert state.state_of(payload) == status.basic_status(pct)
    assert payload["reason"]
