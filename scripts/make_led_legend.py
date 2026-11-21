"""Draw the printed legend card (T-26) as docs/led-legend.pdf.

The card sits beside the plant and tells pupils what each screen of the
Grove 16x2 LCD means. Each screen on the card is drawn from
``led_service.screen_for``, the same text and bar the program sends to the
LCD, so the card and the program cannot drift apart.

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

from plantpulse import lcd  # noqa: E402
from plantpulse.led_service import screen_for  # noqa: E402

OUTPUT = ROOT / "docs" / "led-legend.pdf"

BEZEL = HexColor("#1e1e1e")
SCREEN = HexColor("#1d4ed8")      # White on Blue LCD
CELL_BG = HexColor("#2a5be3")     # unlit pixels, slightly lighter than the screen
PIXEL = HexColor("#f4f7ff")
INK = HexColor("#1d1d1d")
MUTED = HexColor("#5f5f5f")
RULE = HexColor("#d4d4d4")
ACCENT = HexColor("#2e7d32")

ROWS = [
    # (state shown, heading, what to do)
    ("NORMAL", "All good", "The plant is fine. There is nothing to do."),
    ("CHECK", "Check the plant",
     "Something is starting to change. Today, touch the soil and look at the leaves."),
    ("ATTENTION", "The plant needs help",
     "Tell your teacher now. The class web page explains why."),
    ("FAULT", "Sensor problem",
     "The screen cannot tell how the plant is. Tell your teacher."),
]

PAGE_W, PAGE_H = landscape(A5)
MARGIN = 11 * mm
CELL_W, CELL_H, CELL_GAP = 3.8 * mm, 6.2 * mm, 0.5 * mm
SCREEN_PAD = 2 * mm
BEZEL_PAD = 1.8 * mm
SCREEN_W = lcd.COLS * CELL_W + (lcd.COLS - 1) * CELL_GAP + 2 * SCREEN_PAD
SCREEN_H = lcd.ROWS * CELL_H + (lcd.ROWS - 1) * CELL_GAP * 2 + 2 * SCREEN_PAD
LCD_W = SCREEN_W + 2 * BEZEL_PAD
LCD_H = SCREEN_H + 2 * BEZEL_PAD
TEXT_X = MARGIN + LCD_W + 8 * mm
TEXT_W = PAGE_W - MARGIN - TEXT_X


def draw_lcd(c, x, y, rows):
    """The 16x2 LCD with its lower-left corner at (x, y), showing two rows."""
    c.setFillColor(BEZEL)
    c.roundRect(x, y, LCD_W, LCD_H, 1.6 * mm, stroke=0, fill=1)
    c.setFillColor(SCREEN)
    c.rect(x + BEZEL_PAD, y + BEZEL_PAD, SCREEN_W, SCREEN_H, stroke=0, fill=1)
    for r, text in enumerate(rows):
        row = lcd.to_row(text)
        cy = y + BEZEL_PAD + SCREEN_PAD + (lcd.ROWS - 1 - r) * (CELL_H + 2 * CELL_GAP)
        for col, byte in enumerate(row):
            cx = x + BEZEL_PAD + SCREEN_PAD + col * (CELL_W + CELL_GAP)
            c.setFillColor(CELL_BG)
            c.rect(cx, cy, CELL_W, CELL_H, stroke=0, fill=1)
            if byte == lcd.FULL:
                c.setFillColor(PIXEL)
                c.rect(cx, cy, CELL_W, CELL_H, stroke=0, fill=1)
            elif byte == lcd.EMPTY:
                c.setStrokeColor(PIXEL)
                c.setLineWidth(0.9)
                inset = 0.45
                c.rect(cx + inset, cy + inset, CELL_W - 2 * inset, CELL_H - 2 * inset,
                       stroke=1, fill=0)
            elif byte != 0x20:
                c.setFillColor(PIXEL)
                c.setFont("Courier-Bold", 13)
                c.drawCentredString(cx + CELL_W / 2, cy + CELL_H / 2 - 3.4, chr(byte))


def draw_card(path):
    c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("PlantPulse screen legend")
    c.setAuthor("PlantPulse team")
    c.setSubject("What the screen beside the plant means")

    c.setFillColor(white)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    # Header
    top = PAGE_H - MARGIN
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top - 9, "PLANTPULSE")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(MARGIN, top - 31, "What the screen means")

    # Rows
    rows_top = top - 44
    footer_h = 17 * mm
    row_h = (rows_top - MARGIN - footer_h) / len(ROWS)
    for n, (name, heading, action) in enumerate(ROWS):
        row_top = rows_top - n * row_h
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(MARGIN, row_top, PAGE_W - MARGIN, row_top)

        mid = row_top - row_h / 2
        draw_lcd(c, MARGIN, mid - LCD_H / 2, screen_for(name))

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
                 'The screen updates every 5 minutes. Screen blank or "No plant state"? '
                 "Tell your teacher.")

    c.showPage()
    c.save()


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    draw_card(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
