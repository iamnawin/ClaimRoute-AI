"""Shared ReportLab styling and components for the two submission PDFs.

Keeps both documents visually one family and keeps the generators focused on content.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#1F3864")
ACCENT = colors.HexColor("#2E75B6")
INK = colors.HexColor("#1A1A1A")
MUTED = colors.HexColor("#5A5A5A")
RULE = colors.HexColor("#C9D3E0")
BAND = colors.HexColor("#EEF3FA")
WARN_BG = colors.HexColor("#FFF6E5")
WARN_EDGE = colors.HexColor("#D9A441")

PAGE_W, PAGE_H = A4
MARGIN = 17 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=26, leading=30, textColor=NAVY, alignment=TA_LEFT,
                                spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="Helvetica",
                                   fontSize=12.5, leading=17, textColor=ACCENT, spaceAfter=12),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="Helvetica-Bold",
                             fontSize=15, leading=19, textColor=NAVY, spaceBefore=13,
                             spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold",
                             fontSize=11.5, leading=15, textColor=INK, spaceBefore=9,
                             spaceAfter=4),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica",
                               fontSize=9.6, leading=14, textColor=INK, spaceAfter=6),
        "small": ParagraphStyle("small", parent=base["Normal"], fontName="Helvetica",
                                fontSize=8.2, leading=11.5, textColor=MUTED, spaceAfter=5),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontName="Helvetica",
                               fontSize=8.3, leading=11, textColor=INK),
        "cellb": ParagraphStyle("cellb", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=8.3, leading=11, textColor=colors.white),
        "pull": ParagraphStyle("pull", parent=base["Normal"], fontName="Helvetica-Oblique",
                               fontSize=11.5, leading=16, textColor=NAVY, spaceAfter=8),
        "mono": ParagraphStyle("mono", parent=base["Normal"], fontName="Courier",
                               fontSize=7.8, leading=10.6, textColor=INK),
        "center": ParagraphStyle("center", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=9, leading=12, alignment=TA_CENTER, textColor=INK),
    }


S = styles()


def para(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def table(rows: list[list], widths: list[float], align: dict[int, str] | None = None,
          font_size: float = 8.3) -> Table:
    """Header-banded table. Row 0 is the header."""
    data = []
    for r_idx, row in enumerate(rows):
        rendered = []
        for cell in row:
            if isinstance(cell, Paragraph):
                rendered.append(cell)
            else:
                style = "cellb" if r_idx == 0 else "cell"
                rendered.append(Paragraph(str(cell), S[style]))
        data.append(rendered)

    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
    ]
    for col, how in (align or {}).items():
        cmds.append(("ALIGN", (col, 1), (col, -1), how.upper()))
    t.setStyle(TableStyle(cmds))
    return t


class Rule(Flowable):
    """Thin horizontal rule."""

    def __init__(self, width: float, color=RULE, thickness: float = 0.7):
        super().__init__()
        self.width = width
        self.color = color
        self.thickness = thickness
        self.height = thickness

    def draw(self) -> None:
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 0, self.width, 0)


class MetricStrip(Flowable):
    """A row of headline metric tiles."""

    def __init__(self, items: list[tuple[str, str]], width: float, height: float = 26 * mm):
        super().__init__()
        self.items = items
        self.width = width
        self.height = height

    def draw(self) -> None:
        c = self.canv
        n = len(self.items)
        gap = 3.2 * mm
        w = (self.width - gap * (n - 1)) / n
        for i, (value, label) in enumerate(self.items):
            x = i * (w + gap)
            c.setFillColor(BAND)
            c.setStrokeColor(RULE)
            c.setLineWidth(0.6)
            c.roundRect(x, 0, w, self.height, 2.2 * mm, stroke=1, fill=1)
            c.setFillColor(NAVY)
            size = 16 if len(value) <= 8 else (13 if len(value) <= 12 else 10.5)
            c.setFont("Helvetica-Bold", size)
            c.drawCentredString(x + w / 2, self.height - 10.5 * mm, value)
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 6.9)
            for j, line in enumerate(_wrap(label, int(w / (2.05 * mm)))[:3]):
                c.drawCentredString(x + w / 2, self.height - 15.4 * mm - j * 3.5 * mm, line)


class CalloutBox(Flowable):
    """Bordered box used for the limitations panel."""

    def __init__(self, title: str, lines: list[str], width: float,
                 bg=WARN_BG, edge=WARN_EDGE):
        super().__init__()
        self.title = title
        self.lines = lines
        self.width = width
        self.bg = bg
        self.edge = edge
        self._wrapped: list[str] = []
        for line in lines:
            self._wrapped.extend(_wrap(line, int(width / (1.72 * mm))))
        self.height = 9 * mm + len(self._wrapped) * 4.1 * mm

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(self.bg)
        c.setStrokeColor(self.edge)
        c.setLineWidth(1.0)
        c.roundRect(0, 0, self.width, self.height, 2 * mm, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#7A5200"))
        c.setFont("Helvetica-Bold", 9.6)
        c.drawString(4.5 * mm, self.height - 6 * mm, self.title)
        c.setFillColor(INK)
        c.setFont("Helvetica", 8.1)
        for i, line in enumerate(self._wrapped):
            c.drawString(4.5 * mm, self.height - 10.6 * mm - i * 4.1 * mm, line)


class FlowDiagram(Flowable):
    """Vertical or horizontal stage-flow diagram drawn natively (no image assets)."""

    def __init__(self, stages: list[str], width: float, note: str | None = None,
                 columns: int = 3, box_h: float = 11 * mm):
        super().__init__()
        self.stages = stages
        self.width = width
        self.note = note
        self.columns = columns
        self.box_h = box_h
        self.rows = (len(stages) + columns - 1) // columns
        self.height = self.rows * (box_h + 6.5 * mm) + (5 * mm if note else 0)

    def draw(self) -> None:
        c = self.canv
        gap = 4 * mm
        w = (self.width - gap * (self.columns - 1)) / self.columns
        top = self.height - (5 * mm if self.note else 0)

        for idx, stage in enumerate(self.stages):
            r, col = divmod(idx, self.columns)
            x = col * (w + gap)
            y = top - (r + 1) * self.box_h - r * 6.5 * mm
            c.setFillColor(BAND if idx % 2 == 0 else colors.white)
            c.setStrokeColor(ACCENT)
            c.setLineWidth(0.9)
            c.roundRect(x, y, w, self.box_h, 1.8 * mm, stroke=1, fill=1)
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 7.4)
            lines = _wrap(stage, int(w / (1.62 * mm)))[:2]
            for j, line in enumerate(lines):
                c.drawCentredString(x + w / 2, y + self.box_h / 2 + (2.2 * mm if len(lines) > 1 else -1 * mm) - j * 3.6 * mm, line)

            if idx < len(self.stages) - 1:
                c.setStrokeColor(ACCENT)
                c.setLineWidth(1.1)
                if col < self.columns - 1:
                    c.line(x + w, y + self.box_h / 2, x + w + gap, y + self.box_h / 2)
                    _arrow(c, x + w + gap, y + self.box_h / 2, "right")
                else:
                    c.line(x + w / 2, y, x + w / 2, y - 6.5 * mm / 2)
                    c.line(x + w / 2, y - 6.5 * mm / 2, w / 2, y - 6.5 * mm / 2)
                    c.line(w / 2, y - 6.5 * mm / 2, w / 2, y - 6.5 * mm)
                    _arrow(c, w / 2, y - 6.5 * mm, "down")

        if self.note:
            c.setFillColor(MUTED)
            c.setFont("Helvetica-Oblique", 7.2)
            c.drawString(0, 0.5 * mm, self.note)


class BarChartFlowable(Flowable):
    """Simple labelled bar chart for scale/cost visuals."""

    def __init__(self, items: list[tuple[str, float, str]], width: float,
                 height: float = 40 * mm, title: str | None = None):
        super().__init__()
        self.items = items
        self.width = width
        self.height = height + (5 * mm if title else 0)
        self.plot_h = height
        self.title = title

    def draw(self) -> None:
        c = self.canv
        top = self.height
        if self.title:
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(0, top - 3.5 * mm, self.title)
            top -= 6 * mm

        peak = max(v for _, v, _ in self.items) or 1.0
        n = len(self.items)
        gap = 5 * mm
        w = (self.width - gap * (n - 1)) / n
        base = 9 * mm

        for i, (label, value, caption) in enumerate(self.items):
            x = i * (w + gap)
            h = max((value / peak) * (top - base - 6 * mm), 0.6 * mm)
            c.setFillColor(ACCENT if i % 2 == 0 else NAVY)
            c.rect(x, base, w, h, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 7.6)
            c.drawCentredString(x + w / 2, base + h + 1.6 * mm, caption)
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 7.2)
            for j, line in enumerate(_wrap(label, int(w / (1.7 * mm)))[:2]):
                c.drawCentredString(x + w / 2, base - 3.4 * mm - j * 3.2 * mm, line)

        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(0, base, self.width, base)


def _arrow(c, x: float, y: float, direction: str) -> None:
    size = 1.5 * mm
    c.setFillColor(ACCENT)
    p = c.beginPath()
    if direction == "right":
        p.moveTo(x, y)
        p.lineTo(x - size, y + size * 0.72)
        p.lineTo(x - size, y - size * 0.72)
    else:
        p.moveTo(x, y)
        p.lineTo(x - size * 0.72, y + size)
        p.lineTo(x + size * 0.72, y + size)
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def _wrap(text: str, max_chars: int) -> list[str]:
    max_chars = max(max_chars, 6)
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build(path, title: str, subject: str, story: list, footer_left: str) -> None:
    """Render the story with a consistent footer and document metadata."""
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=15 * mm, bottomMargin=16 * mm,
        title=title, author="ClaimRoute AI", subject=subject,
        creator="ClaimRoute AI submission generator",
    )

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, 11.5 * mm, PAGE_W - MARGIN, 11.5 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.2)
        canvas.drawString(MARGIN, 7.8 * mm, footer_left)
        canvas.drawRightString(PAGE_W - MARGIN, 7.8 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


__all__ = [
    "S", "para", "table", "Rule", "MetricStrip", "CalloutBox", "FlowDiagram",
    "BarChartFlowable", "build", "CONTENT_W", "KeepTogether", "Spacer", "mm",
    "NAVY", "ACCENT", "INK", "MUTED", "colors",
]
