"""Builds the PDF report (ReportLab). Pure formatting: only values present in the ScanResult are printed;
anything missing is stated as missing, never invented."""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

from ..core.connectivity import ConnectivityResult
from ..core.models import InfoField, InfoSection, Status, format_timestamp
from ..core.scan import ScanResult
from ..version import APP_NAME, __version__
from .fonts import BOLD, ITALIC, REGULAR, TextSanitizer, register_fonts

REPORT_TITLE = "PC Hardware & Network Report"
ACCENT = colors.HexColor("#2563EB")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#4B5563")
RULE = colors.HexColor("#D8DEE9")
HEAD_BG = colors.HexColor("#E5EAF3")
ZEBRA = colors.HexColor("#F7F9FC")

LIMITATIONS = [
    "This report is a snapshot of the moment the scan ran. Memory in use, frequencies, connections and listening "
    "programs change constantly.",
    "Values come from Windows (registry, CIM/PowerShell, networking APIs) and the psutil library. They are only as "
    "accurate as what Windows and the hardware's firmware report; PCInsight cannot verify them independently.",
    "\"Unavailable\" means PCInsight could not retrieve a value; it does not mean the component is absent. "
    "\"Not exposed by Windows\" means no supported interface exists (for example the motherboard chipset), so nothing "
    "was guessed.",
    "Storage health is Windows' own summary status. It is not a SMART analysis and does not predict failure. Free "
    "space is unrelated to disk health.",
    "Network configuration is read locally. Connectivity tests, if present, are separate, were run at the time shown, "
    "and only show whether a path worked at that moment.",
    "Listening ports are read from this computer's own socket table only. \"Listening locally\" does not mean other "
    "computers can reach a port; firewalls, routers and networks decide that and were not tested. A port with no "
    "listener is not proven closed from outside. UDP endpoints are never classified as open or closed.",
    "Some process names are hidden by Windows unless PCInsight runs as administrator, which is not required.",
    "This report may contain identifiers such as the computer name, IP addresses and MAC addresses. PCInsight keeps "
    "it on this PC; review it before sharing.",
]


@dataclass
class ReportOptions:
    paper: str = "A4"                     # "A4" or "Letter"
    include_network: bool = True
    include_ports: bool = True
    include_connectivity: bool = True

    def page_size(self):
        return LETTER if self.paper.lower() == "letter" else A4


MAX_TEXT_CHARS = 2000   # real Windows device names are at most a few hundred characters


class _NumberedCanvas(canvas.Canvas):
    """Two-pass canvas so every page can print 'Page X of Y'."""

    footer_left = ""
    header_left = ""
    header_right = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []

    def showPage(self):  # noqa: N802 (ReportLab API)
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total: int) -> None:
        w, h = self._pagesize
        self.saveState()
        self.setStrokeColor(RULE)
        self.setLineWidth(0.6)
        self.line(18 * mm, h - 15 * mm, w - 18 * mm, h - 15 * mm)
        self.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
        self.setFont(BOLD, 8)
        self.setFillColor(ACCENT)
        self.drawString(18 * mm, h - 11.5 * mm, self.header_left)
        self.setFont(REGULAR, 8)
        self.setFillColor(MUTED)
        self.drawRightString(w - 18 * mm, h - 11.5 * mm, self.header_right)
        self.drawString(18 * mm, 9.5 * mm, self.footer_left)
        self.drawRightString(w - 18 * mm, 9.5 * mm, f"Page {self._pageNumber} of {total}")
        self.restoreState()


def _styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName=REGULAR, textColor=INK, alignment=TA_LEFT, splitLongWords=1)
    return {
        "title": ParagraphStyle("title", fontSize=26, leading=30, fontName=BOLD, textColor=ACCENT, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", fontSize=14, leading=18, fontName=REGULAR, textColor=INK, spaceAfter=8),
        "h1": ParagraphStyle("h1", fontSize=15, leading=19, fontName=BOLD, textColor=INK, spaceBefore=14,
                             spaceAfter=6, keepWithNext=1),
        "h2": ParagraphStyle("h2", fontSize=11, leading=14, fontName=BOLD, textColor=INK, spaceBefore=10,
                             spaceAfter=3, keepWithNext=1),
        "body": ParagraphStyle("body", fontSize=9, leading=12.5, spaceAfter=4, **base),
        "muted": ParagraphStyle("muted", fontSize=8, leading=11, spaceAfter=3, **{**base, "textColor": MUTED}),
        "cell": ParagraphStyle("cell", fontSize=8, leading=10.5, **base),
        "cellb": ParagraphStyle("cellb", fontSize=8, leading=10.5, **{**base, "fontName": BOLD}),
        "cellm": ParagraphStyle("cellm", fontSize=7.5, leading=9.5, **{**base, "textColor": MUTED}),
        "celli": ParagraphStyle("celli", fontSize=8, leading=10.5, **{**base, "fontName": ITALIC, "textColor": MUTED}),
        "head": ParagraphStyle("head", fontSize=8, leading=10.5, **{**base, "fontName": BOLD}),
        "bullet": ParagraphStyle("bullet", fontSize=9, leading=12.5, leftIndent=10, bulletIndent=0, spaceAfter=3, **base),
    }


class _ReportBuilder:
    def __init__(self, result: ScanResult, connectivity: ConnectivityResult | None, options: ReportOptions,
                 generated_at: datetime, app_version: str):
        self.result, self.connectivity, self.opt = result, connectivity, options
        self.generated_at, self.version = generated_at, app_version
        self.st = _styles()
        self.san = TextSanitizer()
        self.page_size = options.page_size()
        self.width = self.page_size[0] - 36 * mm
        self.warnings: list[tuple[str, str, str, str]] = []   # section, item, state, reason

    # -- text helpers ---------------------------------------------------------------------------------
    def para(self, text: object, style: str = "body") -> Paragraph:
        """XML-escape (so names like 'A&B <x>' print literally), sanitise, keep line breaks."""
        clean = self.san.clean(text)
        if len(clean) > MAX_TEXT_CHARS:      # far beyond any real device name; one cell taller than a page cannot be laid out
            clean = (clean[:MAX_TEXT_CHARS] +
                     f" [\u2026 {len(clean) - MAX_TEXT_CHARS:,} more characters are not shown in this report]")
        t = escape(clean).replace("\n", "<br/>")
        return Paragraph(t, self.st[style])

    def value_cell(self, f: InfoField, network_or_ports: bool):
        if f.status is Status.OK:
            return self.para(f.value, "cell")
        words = {Status.UNAVAILABLE: "Unavailable", Status.UNSUPPORTED: "Not exposed by Windows",
                 Status.EMPTY: "Reported as empty"}
        return self.para(words[f.status], "celli")

    def detail_cell(self, f: InfoField):
        text = f.source + (f"\n{f.note}" if f.note else "")
        return self.para(text, "cellm")

    # -- tables ---------------------------------------------------------------------------------------------
    def section_table(self, sec: InfoSection, network_or_ports: bool = False) -> list:
        rows = [[self.para("Item", "head"), self.para("Value", "head"), self.para("Source / note", "head")]]
        for f in sec.fields:
            rows.append([self.para(f.label, "cellb"), self.value_cell(f, network_or_ports), self.detail_cell(f)])
            if f.status in (Status.UNAVAILABLE, Status.UNSUPPORTED) or (
                    f.status is Status.EMPTY and not network_or_ports):
                state = {Status.UNAVAILABLE: "Unavailable", Status.UNSUPPORTED: "Not exposed by Windows",
                         Status.EMPTY: "Reported as empty"}[f.status]
                self.warnings.append((sec.title, f.label, state, f.note or "No reason was reported."))
        return [self.make_table(rows, [0.27, 0.45, 0.28]),]

    def make_table(self, rows: list, fractions: list[float]) -> Table:
        t = Table(rows, colWidths=[self.width * x for x in fractions], repeatRows=1, splitByRow=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("GRID", (0, 0), (-1, -1), 0.4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
        for i in range(2, len(rows), 2):
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
        t.setStyle(TableStyle(style))
        return t

    def section_block(self, sec: InfoSection, network_or_ports: bool = False) -> list:
        out: list = [self.para(sec.title, "h2")]
        if sec.note:
            out.append(self.para(sec.note, "muted"))
        out += self.section_table(sec, network_or_ports)
        return out

    # -- content ------------------------------------------------------------------------------------------------
    def first_ok(self, sec: InfoSection | None, key: str) -> str | None:
        f = sec.get(key) if sec else None
        return f.value if f is not None and f.status is Status.OK else None

    def cover(self) -> list:
        r = self.result
        story: list = [Spacer(1, 4 * mm), self.para(APP_NAME, "title"), self.para(REPORT_TITLE, "subtitle")]
        meta = [["Scan date and time", format_timestamp(r.scanned_at)],
                ["Report generated", format_timestamp(self.generated_at)],
                ["Generated by", f"{APP_NAME} {self.version} (offline; nothing was uploaded)"]]
        story.append(self.kv_table(meta))
        story.append(self.para("At a glance", "h1"))
        hw = r.section
        mem, cpu = hw("memory"), hw("cpu")
        gpus = [v for s in r.sections_for("gpu") if (v := self.first_ok(s, "gpu_name"))]
        disks = [f"{m} ({c})" if c else m for s in r.sections_for("storage")
                 if (m := self.first_ok(s, "model")) for c in [self.first_ok(s, "capacity")]]
        net = hw("network")
        ports = hw("ports")
        sysf = r.system
        glance = [
            ["Computer", self.val(sysf.get("computer_name"))],
            ["Operating system", " ".join(x for x in (self.val(sysf.get("os_edition"), None),
                                                      self.val(sysf.get("os_version"), None)) if x) or "Not available"],
            ["Processor", self.first_ok(cpu, "cpu_name") or "Not collected / not available"],
            ["Memory", (self.first_ok(mem, "installed") or self.first_ok(mem, "total_physical") or "Not collected / not available")],
            ["Graphics", "; ".join(gpus) or "Not collected / not available"],
            ["Storage", "; ".join(disks) or "Not collected / not available"],
            ["Network adapters", self.first_ok(net, "adapters") or "Not collected / not available"],
            ["Listening endpoints", self.ports_glance(ports)],
        ]
        story.append(self.kv_table(glance))
        return story

    def val(self, f: InfoField | None, fallback: str | None = "Not available") -> str | None:
        return f.value if f is not None and f.status is Status.OK else fallback

    def ports_glance(self, ports: InfoSection | None) -> str:
        t, u = self.first_ok(ports, "tcp_count"), self.first_ok(ports, "udp_count")
        return f"{t} TCP listeners, {u} UDP endpoints" if t is not None and u is not None else "Not collected / not available"

    def kv_table(self, rows: list[list[str]]) -> Table:
        data = [[self.para(k, "cellb"), self.para(v, "cell")] for k, v in rows]
        t = Table(data, colWidths=[self.width * 0.27, self.width * 0.73])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
        return t

    def system_part(self) -> list:
        sec = InfoSection("system", "System", self.result.system.fields, self.result.system.collected_at)
        return [self.para("1. System overview", "h1")] + self.section_block(sec)

    def hardware_part(self) -> list:
        skip = {id(x) for x in self.result.network_sections() + self.result.ports_sections()}
        secs = [s for s in self.result.hardware if id(s) not in skip]
        out: list = [self.para("2. Hardware summary", "h1")]
        if not secs:
            out.append(self.para("No hardware data was collected in this scan, so nothing is shown here.", "body"))
            self.warnings.append(("Hardware", "CPU, motherboard, BIOS, memory, graphics, storage",
                                  "Not collected", "No hardware sections are present in the scan result."))
        for s in secs:
            out += self.section_block(s)
        return out

    def network_part(self) -> list:
        out: list = [self.para("3. Network configuration", "h1")]
        secs = self.result.network_sections()
        if not secs:
            out.append(self.para("No network data was collected in this scan, so nothing is shown here.", "body"))
            self.warnings.append(("Network", "Network configuration", "Not collected",
                                  "No network sections are present in the scan result."))
        else:
            out.append(self.para("Local configuration read from this computer at the scan time above. "
                                 "No network traffic was sent to collect it.", "muted"))
            for s in secs:
                out += self.section_block(s, network_or_ports=True)
        out.append(self.para("Connectivity tests", "h2"))
        if self.opt.include_connectivity and self.connectivity is not None:
            out.append(self.para(f"Run separately at {format_timestamp(self.connectivity.ran_at)}. These show only "
                                 "whether a path worked at that moment.", "muted"))
            for s in self.connectivity.sections:
                out += self.section_table(s, network_or_ports=True)
        elif self.opt.include_connectivity:
            out.append(self.para("Connectivity tests were not run, so there are no results to show.", "body"))
        else:
            out.append(self.para("Connectivity test results were left out of this report by choice.", "body"))
        return out

    def ports_part(self) -> list:
        out: list = [self.para("4. Local listening ports", "h1")]
        secs = self.result.ports_sections()
        if not secs:
            out.append(self.para("No port data was collected in this scan, so nothing is shown here.", "body"))
            self.warnings.append(("Listening ports", "Listening ports", "Not collected",
                                  "No port sections are present in the scan result."))
            return out
        out.append(self.para("This computer only. Other computers were not scanned or contacted.", "muted"))
        for s in secs:
            out += self.section_block(s, network_or_ports=True)
        return out

    def warnings_part(self) -> list:
        out: list = [self.para("5. Warnings and unavailable information", "h1")]
        for err in self.result.errors:
            self.warnings.append(("Scan", "Collection problem", "Error", err))
        if self.san.replaced:
            self.warnings.append(("Report", "Text characters", "Replaced",
                                  f"{self.san.replaced} character(s) in names could not be shown in the report font "
                                  "and were replaced with '?'."))
        if not self.warnings:
            out.append(self.para("Every collected value was available. Nothing was reported as unavailable.", "body"))
            return out
        out.append(self.para("Items PCInsight could not retrieve, or that Windows does not provide. "
                             "These are not guesses; they are listed so nothing is silently missing.", "muted"))
        rows = [[self.para(h, "head") for h in ("Section", "Item", "State", "Reason")]]
        for sec, item, state, reason in self.warnings:
            rows.append([self.para(sec, "cell"), self.para(item, "cellb"), self.para(state, "celli"),
                         self.para(reason, "cellm")])
        out.append(self.make_table(rows, [0.2, 0.25, 0.17, 0.38]))
        return out

    def limits_part(self) -> list:
        out: list = [self.para("6. About this scan and its limitations", "h1")]
        for text in LIMITATIONS:
            out.append(Paragraph(escape(text), self.st["bullet"], bulletText="\u2022"))
        return out

    # -- assemble ------------------------------------------------------------------------------------------------
    def build(self) -> bytes:
        story: list = self.cover()
        story += self.system_part() + self.hardware_part()
        story += self.network_part() if self.opt.include_network else [
            self.para("3. Network configuration", "h1"),
            self.para("Network configuration was left out of this report by choice.", "body")]
        story += self.ports_part() if self.opt.include_ports else [
            self.para("4. Local listening ports", "h1"),
            self.para("Listening-port results were left out of this report by choice.", "body")]
        story += self.warnings_part()   # after the sections so it can list everything they flagged
        story += self.limits_part()
        buf = io.BytesIO()
        header_left = f"{APP_NAME}  \u00b7  {REPORT_TITLE}"
        header_right = f"Scan: {format_timestamp(self.result.scanned_at)}"
        footer_left = f"Generated by {APP_NAME} {self.version}  \u00b7  local report, not uploaded"

        class Canvas(_NumberedCanvas):
            pass

        Canvas.header_left, Canvas.header_right, Canvas.footer_left = (
            self.san.clean(header_left), self.san.clean(header_right), self.san.clean(footer_left))
        doc = BaseDocTemplate(buf, pagesize=self.page_size, leftMargin=18 * mm, rightMargin=18 * mm,
                              topMargin=21 * mm, bottomMargin=20 * mm, title=f"{APP_NAME} {REPORT_TITLE}",
                              author=APP_NAME, subject="Hardware and network report", creator=f"{APP_NAME} {self.version}")
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body", leftPadding=0,
                      rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])
        doc.build(story, canvasmaker=Canvas)
        return buf.getvalue()


def build_report_pdf(result: ScanResult, connectivity: ConnectivityResult | None = None,
                     options: ReportOptions | None = None, generated_at: datetime | None = None,
                     app_version: str = __version__) -> bytes:
    register_fonts()
    return _ReportBuilder(result, connectivity, options or ReportOptions(), generated_at or datetime.now(),
                          app_version).build()
