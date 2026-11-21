"""Driver for the Grove 16x2 LCD (White on Blue).

The screen is an I2C device (JHD1802 module, AIP31068 controller, address
0x3E): plug it into one of the I2C ports of the Grove Base HAT, not into a
digital port. Every command or character is one I2C write: control byte
0x80 for a command, 0x40 for a character.

Besides the ASCII characters, the bar on the second row uses two cells:
``FULL`` (the solid block in the character ROM) and ``EMPTY`` (a hollow box
stored in custom character slot 0).

Run on the Pi to check the screen:

    python -m plantpulse.lcd
"""

from __future__ import annotations

import time

from plantpulse import config

COLS, ROWS = 16, 2
COMMAND, DATA = 0x80, 0x40
ROW_ADDRESS = (0x00, 0x40)

FULL = 0xFF   # solid block in the character ROM
EMPTY = 0x00  # custom character 0: hollow box
EMPTY_PATTERN = (0x1F, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1F, 0x00)


def bar(lit, cells=10):
    """A bar of ``cells`` cells with the first ``lit`` full, centred on one row."""
    lit = max(0, min(cells, int(lit)))
    cells_row = bytes([FULL] * lit + [EMPTY] * (cells - lit))
    left = (COLS - cells) // 2
    return b" " * left + cells_row + b" " * (COLS - cells - left)


def to_row(text):
    """Text or bytes as exactly one row: cut or padded with spaces."""
    if isinstance(text, str):
        text = text.encode("ascii", "replace")
    return text[:COLS].ljust(COLS, b" ")


class Lcd:
    """Write two rows of text on the Grove 16x2 LCD.

    The screen is set up on the first write. If a write fails (screen
    unplugged), the error is raised and the next write sets it up again.
    """

    def __init__(self, address=config.LCD_I2C_ADDRESS, bus=None, sleep=time.sleep):
        if bus is None:
            from grove.i2c import Bus

            bus = Bus()
        self._bus = bus
        self._address = address
        self._sleep = sleep
        self._ready = False

    def show(self, line1, line2=""):
        """Show two rows; each is a str (ASCII) or bytes with bar cells."""
        try:
            if not self._ready:
                self._setup()
            for row, text in enumerate((line1, line2)):
                self._command(0x80 | ROW_ADDRESS[row])
                for byte in to_row(text):
                    self._bus.write_byte_data(self._address, DATA, byte)
        except Exception:
            self._ready = False
            raise

    def clear(self):
        self.show("", "")

    def _command(self, value):
        self._bus.write_byte_data(self._address, COMMAND, value)

    def _setup(self):
        self._sleep(0.05)              # the controller needs time after power-up
        for wait in (0.0045, 0.0045, 0.00015, 0):
            self._command(0x28)        # 2 rows, 5x8 dots
            self._sleep(wait)
        self._command(0x0C)            # display on, no cursor, no blink
        self._command(0x06)            # write left to right
        self._command(0x40 | EMPTY << 3)
        for byte in EMPTY_PATTERN:
            self._bus.write_byte_data(self._address, DATA, byte)
        self._command(0x01)            # clear
        self._sleep(0.002)
        self._ready = True


if __name__ == "__main__":
    lcd = Lcd()
    lcd.show("PlantPulse LCD", "works!")
    time.sleep(2)
    for lit in range(11):
        lcd.show(f"Bar: {lit} of 10", bar(lit))
        time.sleep(0.5)
    print("If you read the text and saw the bar fill up, the screen works.")
