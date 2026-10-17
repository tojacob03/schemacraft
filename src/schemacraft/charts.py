"""Charts drawn for map walls: exact pixel size, no anti-aliasing, only map colours.

A spec is a dict:
  {"type": "bars", "max": 100, "ref": {"value": 56.8, "label": "his average"},
   "panels": [{"title": "...", "bars": [{"label": "...", "value": 39.3, "text": "39.3 %", "highlight": true}]}]}
  {"type": "table", "columns": ["Card", "G1", "G2"], "widths": [0.4, 0.3, 0.3],
   "rows": [["Fireball", "24.2 %", "27.8 %"]], "bars": [1, 2], "max": 40}
Bar panels sit side by side. In a table, the columns listed in "bars" get a data bar behind
their number. Every chart picks the largest font that fits its wall.
"""

import re
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from schemacraft.mapart import colour  # noqa: E402

PAPER = colour(255, 255, 255)
INK = colour(25, 25, 25)
FAINT = colour(199, 199, 199)
BAR = colour(102, 153, 216)
ACCENT = colour(216, 127, 51)
SUBTLE = colour(112, 112, 112)

SIZES = range(30, 12, -1)  # px; below about 13 px map text stops being readable from a few blocks
CHAR = 0.64  # average glyph width of DejaVu Sans Bold, in font sizes
PAD = 16


def _rgb(c):
    return tuple(v / 255 for v in c)


def render(spec: dict, width: int, height: int) -> np.ndarray:
    """RGB image (height, width, 3) of the chart."""
    kind = spec["type"]
    if kind not in ("bars", "table"):
        raise ValueError(f"unknown chart type {kind}")
    fits = _bars_fit if kind == "bars" else _table_fit
    font = next((f for f in SIZES if fits(spec, width, height, f)), SIZES[-1])
    with plt.rc_context({"text.antialiased": False, "lines.antialiased": False, "patch.antialiased": False,
                         "font.family": "DejaVu Sans", "font.weight": "bold"}):
        fig = plt.figure(figsize=(width / 100, height / 100), dpi=100, facecolor=_rgb(PAPER))
        ax = fig.add_axes((0, 0, 1, 1))
        ax.set_xlim(0, width)
        ax.set_ylim(height, 0)
        ax.axis("off")
        if kind == "bars":
            w = width / len(spec["panels"])
            for i, panel in enumerate(spec["panels"]):
                _bars(ax, spec, panel, i * w, 0, w, height, font)
        else:
            _table(ax, spec, 0, 0, width, height, font)
        fig.canvas.draw()
        image = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
        plt.close(fig)
    return image


def _text(ax, x, y, s, size, color=INK, **kw):
    ax.text(x, y, s, fontsize=size * 0.72, color=_rgb(color), va="center", **kw)  # px -> pt at 100 dpi


def _width(s: str, font: int) -> float:
    return len(s) * font * CHAR


# bars ------------------------------------------------------------------------------------------

def _bars_geometry(spec, panel, w, h, font):
    bars = panel["bars"]
    title = font * 2.4 if panel.get("title") else 0
    label_w = max(_width(b["label"], font) for b in bars) + 10
    text_w = max(_width(b.get("text", ""), font) for b in bars) + 10
    bar_w = w - 2 * PAD - label_w - text_w
    ref = font * 1.6 if spec.get("ref") else 0
    row = (h - 2 * PAD - title - ref) / len(bars)
    return title, label_w, bar_w, ref, row


def _bars_fit(spec, width, height, font) -> bool:
    w = width / len(spec["panels"])
    for panel in spec["panels"]:
        _, _, bar_w, _, row = _bars_geometry(spec, panel, w, height, font)
        if bar_w < w * 0.3 or row < font * 1.8:
            return False
    return True


def _bars(ax, spec, panel, x0, y0, w, h, font):
    bars = panel["bars"]
    title, label_w, bar_w, ref_h, row = _bars_geometry(spec, panel, w, h, font)
    row = min(row, font * 2.8)
    top = y0 + PAD
    if panel.get("title"):
        _text(ax, x0 + PAD, top + font, panel["title"], font + 4)
        top += title
    bar_x = x0 + PAD + label_w
    vmax = spec.get("max") or max(b["value"] for b in bars) or 1
    for i, b in enumerate(bars):
        cy = top + row * i + row / 2
        _text(ax, bar_x - 10, cy, b["label"], font, ha="right")
        ax.add_patch(Rectangle((bar_x, cy - row * 0.32), bar_w, row * 0.64, color=_rgb(FAINT), lw=0))
        length = bar_w * min(max(b["value"], 0), vmax) / vmax
        ax.add_patch(Rectangle((bar_x, cy - row * 0.32), length, row * 0.64,
                               color=_rgb(ACCENT if b.get("highlight") else BAR), lw=0))
        if b.get("text"):
            _text(ax, bar_x + bar_w + 10, cy, b["text"], font)
    if spec.get("ref"):
        x = bar_x + bar_w * spec["ref"]["value"] / vmax
        bottom = top + row * len(bars)
        ax.add_patch(Rectangle((x - 1, top), 3, bottom - top, color=_rgb(INK), lw=0))
        _text(ax, x, bottom + font, spec["ref"]["label"], font - 2, ha="center")


# table -----------------------------------------------------------------------------------------

def _cells(spec, width, font):
    widths = spec.get("widths") or [1 / len(spec["columns"])] * len(spec["columns"])
    inner = width - 2 * PAD
    rows = []
    for row in spec["rows"]:
        rows.append([textwrap.wrap(str(v), max(4, int(wd * inner / (font * CHAR)) - 1)) or [""]
                     for v, wd in zip(row, widths)])
    return widths, inner, rows


def _table_fit(spec, width, height, font) -> bool:
    _, _, rows = _cells(spec, width, font)
    line = font * 1.3
    used = PAD * 2 + font * 2 + 10 + sum(max(len(c) for c in r) * line + 8 for r in rows)
    return used <= height


def _table(ax, spec, x0, y0, w, h, font):
    widths, inner, rows = _cells(spec, w, font)
    xs = [x0 + PAD + sum(widths[:i]) * inner for i in range(len(widths))]
    bar_cols = set(spec.get("bars", []))
    numbers = [[_number(v) for v in r] for r in spec["rows"]]
    vmax = spec.get("max") or max((n for r in numbers for i, n in enumerate(r) if i in bar_cols and n), default=1)
    line = font * 1.3
    y = y0 + PAD + font
    for x, name in zip(xs, spec["columns"]):
        _text(ax, x + 4, y, name, font, color=SUBTLE)
    y += font
    ax.add_patch(Rectangle((x0 + PAD, y), inner, 2, color=_rgb(INK), lw=0))
    y += 8
    for cells, nums in zip(rows, numbers):
        n = max(len(c) for c in cells)
        height = n * line + 8
        for i, (x, lines) in enumerate(zip(xs, cells)):
            if i in bar_cols and nums[i] is not None:
                cell_w = widths[i] * inner - 8
                ax.add_patch(Rectangle((x, y + 3), cell_w * min(nums[i] / vmax, 1), height - 6,
                                       color=_rgb(BAR), lw=0))
            for k, s in enumerate(lines):
                _text(ax, x + 4, y + 4 + line * k + line / 2, s, font)
        y += height
        ax.add_patch(Rectangle((x0 + PAD, y - 1), inner, 1, color=_rgb(FAINT), lw=0))


def _number(value):
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    return float(m.group().replace(",", ".")) if m else None
