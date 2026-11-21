"""Driver for the Grove LED Bar v2 (MY9221 chip, 10 segments).

The bar uses two pins of one Grove digital port: data on the port's pin and
clock on the next one (port D16: GPIO 16 data, GPIO 17 clock).

The MY9221 reads one data bit on every clock edge, rising and falling, so
the clock is toggled once per bit, as in Seeed's reference driver. A frame
is a 16-bit command word, one 16-bit brightness word per channel (10
segments plus 2 unused channels) and then the latch sequence.

Segment 0 is the first segment lit by ``level``.

Run on the Pi to light 0 to 10 segments in turn:

    python -m plantpulse.led_bar
"""

from __future__ import annotations

import time

from plantpulse import config

SEGMENTS = 10
CHANNELS = 12          # the chip has 12; the bar wires the first 10
COMMAND = 0x0000       # 8-bit grayscale mode, default settings
ON = 0x00FF            # full brightness in 8-bit mode
OFF = 0x0000
LATCH_WAIT_S = 0.0003  # the chip needs the clock still for over 220 us before latching


class LedBar:
    """Light any set of the 10 segments of a Grove LED Bar."""

    def __init__(self, pin=config.LED_BAR_PIN, gpio_class=None, sleep=time.sleep):
        if gpio_class is None:
            from grove.gpio import GPIO as gpio_class
        self._data = gpio_class(pin, gpio_class.OUT)
        self._clock = gpio_class(pin + 1, gpio_class.OUT)
        self._sleep = sleep
        self._clock_level = 0
        self._clock.write(0)

    def show(self, segments):
        """Light the segments that are true in a sequence of 10 booleans."""
        segments = list(segments)
        if len(segments) != SEGMENTS:
            raise ValueError(f"expected {SEGMENTS} segments, got {len(segments)}")
        self._send_word(COMMAND)
        for lit in segments:
            self._send_word(ON if lit else OFF)
        for _ in range(CHANNELS - SEGMENTS):
            self._send_word(OFF)
        self._latch()

    def level(self, count):
        """Light the first ``count`` segments (0 to 10) and turn off the rest."""
        count = max(0, min(SEGMENTS, int(count)))
        self.show(i < count for i in range(SEGMENTS))

    def off(self):
        self.level(0)

    def _send_word(self, word):
        for bit in range(15, -1, -1):
            self._data.write((word >> bit) & 1)
            self._clock_level ^= 1
            self._clock.write(self._clock_level)

    def _latch(self):
        self._data.write(0)
        self._sleep(LATCH_WAIT_S)
        for _ in range(4):
            self._data.write(1)
            self._data.write(0)
        self._sleep(LATCH_WAIT_S)


if __name__ == "__main__":
    bar = LedBar()
    try:
        for count in range(SEGMENTS + 1):
            print(f"{count} segment(s)")
            bar.level(count)
            time.sleep(0.5)
    finally:
        bar.off()
