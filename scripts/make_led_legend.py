"""Draw the printed LED legend card (T-26) as docs/led-legend.pdf.

The card sits beside the plant and tells pupils what each LED bar pattern
means. The segment counts come from plantpulse/led_service.py, so the card
and the LED program cannot drift apart.

    pip install -r requirements-dev.txt
    python scripts/make_led_legend.py

Print on A5 (or A4 at 100 %, then cut), landscape, and laminate it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plantpulse.led_bar import SEGMENTS  # noqa: E402
from plantpulse.led_service import PATTERNS  # noqa: E402

OUTPUT = ROOT / "docs" / "led-legend.pdf"

# Grove LED Bar v2 colours, in the order ``level`` lights them:
# seven green, one light green, one yellow, one red.
SEGMENT_COLOURS = ["#22b14c"] * 7 + ["#9bd34a", "#ffc20e", "#ed1c24"]
UNLIT = HexColor("#5a5a5a")
HOUSING = HexColor("#262626")
INK = HexColor("#1d1d1d")
MUTED = HexColor("#5f5f5f")
RULE = HexColor("#d4d4d4")
ACCENT = HexColor("#2e7d32")

ROWS = [
    # (segments lit, blinking, heading, what to do)
    (PATTERNS["NORMAL"], False, "All good",
     "The plant is fine. There is nothing to do."),
    (PATTERNS["CHECK"], False, "Check the plant",
     "Something is starting to change. Today, touch the soil and look at the leaves."),
    (PATTERNS["ATTENTION"], False, "The plant needs help",
     "Tell your teacher now. The class web page explains why."),
    (SEGMENTS, True, "Blinking: sensor problem",
     "Do not trust the bar. Tell your teacher."),
]

PAGE_W, PAGE_H = landscape(A5)
MARGIN = 11 * mm
SEG_W, SEG_H, SEG_GAP = 5.6 * mm, 11 * mm, 1.4 * mm
PAD = 2 * mm
BAR_W = SEGMENTS * SEG_W + (SEGMENTS - 1) * SEG_GAP + 2 * PAD
TEXT_X = MARGIN + BAR_W + 9 * mm
TEXT_W = PAGE_W - MARGIN - TEXT_X


def draw_bar(c, x, y, lit, blinking):
    """LED bar with its lower-left corner at (x, y)."""
    c.setFillColor(HOUSING)
    c.roundRect(x, y, BAR_W, SEG_H + 2 * PAD, 2 * mm, stroke=0, fill=1)
    for i in range(SEGMENTS):
        sx = x + PAD + i * (SEG_W + SEG_GAP)
        c.setFillColor(HexColor(SEGMENT_COLOURS[i]) if i < lit else UNLIT)
        c.roundRect(sx, y + PAD, SEG_W, SEG_H, 0.8 * mm, stroke=0, fill=1)
    if blinking:
        # Motion marks on both ends: the whole bar goes on and off.
        c.setStrokeColor(INK)
        c.setLineWidth(1.1)
        cy = y + PAD + SEG_H / 2
        for k in range(3):
            r = (3 + 1.5 * k) * mm
            for cx, start in ((x + BAR_W, -40), (x, 140)):
                c.arc(cx - r, cy - r, cx + r, cy + r, start, 80)


def draw_card(path):
    c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("PlantPulse LED legend")
    c.setAuthor("PlantPulse team")
    c.setSubject("What the LED bar beside the plant means")

    c.setFillColor(white)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    # Header
    top = PAGE_H - MARGIN
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top - 9, "PLANTPULSE")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(MARGIN, top - 31, "What the light bar means")

    # Rows
    rows_top = top - 44
    footer_h = 17 * mm
    row_h = (rows_top - MARGIN - footer_h) / len(ROWS)
    bar_h = SEG_H + 2 * PAD
    for n, (lit, blinking, heading, action) in enumerate(ROWS):
        row_top = rows_top - n * row_h
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(MARGIN, row_top, PAGE_W - MARGIN, row_top)

        mid = row_top - row_h / 2
        draw_bar(c, MARGIN, mid - bar_h / 2, lit, blinking)

        lines = simpleSplit(action, "Helvetica", 11, TEXT_W)
        block = 16 + 13.5 * len(lines)
        y = mid + block / 2 - 13
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(TEXT_X, y, heading)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 11)
        for line in lines:
            y -= 13.5
            c.drawString(TEXT_X, y, line)
    c.setStrokeColor(RULE)
    c.line(MARGIN, rows_top - len(ROWS) * row_h, PAGE_W - MARGIN, rows_top - len(ROWS) * row_h)

    # Footer
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10)
    y = MARGIN + footer_h - 22
    c.drawString(MARGIN, y, "Before you water, always touch the soil first.")
    c.setFont("Helvetica", 9.5)
    c.setFillColor(MUTED)
    c.drawString(MARGIN, y - 13,
                 "The bar updates every 5 minutes. Bar completely off? "
                 "The system is off or starting: tell your teacher.")

    c.showPage()
    c.save()


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    draw_card(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
