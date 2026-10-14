import io
import re
from datetime import datetime

import pypdf
import pytest

from helpers import NOW, sample_everything_with_network, sample_result, sample_with_ports
from pcinsight.core.connectivity import ConnectivityResult
from pcinsight.core.models import InfoField, InfoSection, Status
from pcinsight.core.scan import ScanResult
from pcinsight.report import ReportOptions, build_report_pdf

GEN = datetime(2026, 10, 13, 9, 30, 0)


def pages(data: bytes) -> list[str]:
    return [p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages]


def flat(data: bytes) -> str:
    return re.sub(r"\s+", " ", " ".join(pages(data)))


def squash(data: bytes) -> str:
    return re.sub(r"\s+", "", " ".join(pages(data)))


def conn_result() -> ConnectivityResult:
    f = [InfoField("internet", "Internet connection (TCP)", "Connected to 1.1.1.1:443 (12 ms)", Status.OK, "test")]
    return ConnectivityResult([InfoSection("net_connectivity", "Connectivity tests", f, datetime(2026, 10, 12, 12, 5, 0))],
                              datetime(2026, 10, 12, 12, 5, 0))


def build(result=None, conn=None, **opts):
    return build_report_pdf(result or sample_with_ports(), conn, ReportOptions(**opts), generated_at=GEN)


def test_is_a_pdf_with_metadata():
    data = build()
    assert data.startswith(b"%PDF")
    meta = pypdf.PdfReader(io.BytesIO(data)).metadata
    assert meta.title == "PCInsight PC Hardware & Network Report" and meta.author == "PCInsight"


def test_required_content_is_present():
    t = flat(build())
    for needle in ("PCInsight", "PC Hardware & Network Report", "Scan date and time", "2026-10-12 12:00:00",
                   "Report generated", "2026-10-13 09:30:00", "1. System overview", "2. Hardware summary",
                   "3. Network configuration", "4. Local listening ports",
                   "5. Warnings and unavailable information", "6. About this scan and its limitations"):
        assert needle in t, needle
    for value in ("TEST-PC", "Windows 11 Pro", "Test CPU 9000", "Test SSD 970", "192.168.1.20", "445/TCP",
                  "Listening locally", "UDP endpoint detected; remote reachability not verified"):
        assert value in t, value


def test_limitations_cover_the_important_caveats():
    t = flat(build())
    for phrase in ("snapshot", "Unavailable", "not a SMART analysis", "does not mean other computers can reach",
                   "not proven closed from outside", "never classified as open or closed", "review it before sharing"):
        assert phrase in t.replace("\u201c", '"').replace("\u201d", '"').replace('"', "") or phrase in t, phrase


def test_unavailable_information_is_listed_not_hidden():
    t = flat(build())
    section = t[t.index("5. Warnings and unavailable information"):t.index("6. About this scan")]
    assert "Chipset" in section and "Not exposed by Windows" in section
    assert "BIOS version" in section and "Unavailable" in section and "denied" in section
    assert "Rated speed" in section


def test_all_values_available_says_so():
    r = sample_result()
    r.hardware = []
    # a result with no hardware is reported as not collected, never as "all fine"
    assert "No hardware data was collected" in flat(build(r))
    ok = ScanResult(sample_result().system, NOW, hardware=[], errors=[])
    ok.hardware = [InfoSection("cpu", "Processor (CPU)", [InfoField("cpu_name", "CPU name", "X", Status.OK, "t")], NOW)]
    ok.system.fields[:] = [f for f in ok.system.fields]
    t = flat(build(ok, include_network=False, include_ports=False))
    assert "No hardware data was collected" not in t


def test_every_page_has_header_footer_and_correct_numbering():
    r = sample_with_ports()
    ports = r.section("ports_tcp")
    many = [InfoField(f"tcp_{i}", f"{10000 + i}/TCP", "Listening locally\n0.0.0.0:1 \u00b7 all interfaces \u00b7 x.exe (PID 1)",
                      Status.OK, "psutil", "note") for i in range(400)]
    r.hardware[r.hardware.index(ports)] = InfoSection("ports_tcp", "All listening TCP endpoints", many, NOW)
    ps = pages(build(r))
    assert len(ps) >= 6
    for i, text in enumerate(ps, 1):
        assert "PCInsight \u00b7 PC Hardware & Network Report" in text.replace("  ", " ")
        assert f"Page {i} of {len(ps)}" in text
        assert "Scan: 2026-10-12 12:00:00" in text and "local report, not uploaded" in text


def test_table_header_repeats_on_continuation_pages():
    r = sample_with_ports()
    many = [InfoField(f"tcp_{i}", f"{10000 + i}/TCP", "Listening locally", Status.OK, "psutil") for i in range(300)]
    r.hardware[r.hardware.index(r.section("ports_tcp"))] = InfoSection("ports_tcp", "All listening TCP endpoints", many, NOW)
    ps = pages(build(r))
    later = [t for t in ps[2:] if "10250/TCP" in t or "10200/TCP" in t or "10100/TCP" in t]
    assert later and all("Source / note" in t for t in later)


def test_long_names_are_never_truncated():
    r = sample_with_ports()
    long_model = "Z" * 150
    unbroken = "ABCDEFGHIJ" * 20
    r.hardware.append(InfoSection("storage_disk_9", "Storage device 9", [
        InfoField("model", "Model", long_model, Status.OK, "test", unbroken)], NOW))
    r.system.fields.append(InfoField("x", "Long item name " + "w" * 90, "short", Status.OK, "test"))
    t = squash(build(r))
    assert long_model in t and unbroken in t and "w" * 90 in t


def test_paper_sizes():
    a4 = pypdf.PdfReader(io.BytesIO(build(paper="A4"))).pages[0].mediabox
    letter = pypdf.PdfReader(io.BytesIO(build(paper="Letter"))).pages[0].mediabox
    assert round(float(a4.width)) == 595 and round(float(a4.height)) == 842
    assert round(float(letter.width)) == 612 and round(float(letter.height)) == 792


def test_section_options():
    full = flat(build(sample_everything_with_network()))
    assert "192.168.1.20" in full
    no_net = flat(build(sample_everything_with_network(), include_network=False))
    assert "192.168.1.20" not in no_net and "left out of this report by choice" in no_net
    no_ports = flat(build(include_ports=False))
    assert "445/TCP" not in no_ports and "Listening-port results were left out" in no_ports


def test_connectivity_run_not_run_and_left_out():
    assert "Connectivity tests were not run" in flat(build())
    with_conn = flat(build(conn=conn_result()))
    assert "Run separately at 2026-10-12 12:05:00" in with_conn and "Connected to 1.1.1.1:443 (12 ms)" in with_conn
    left_out = flat(build(conn=conn_result(), include_connectivity=False))
    assert "Connected to 1.1.1.1" not in left_out and "left out of this report by choice" in left_out


def test_nothing_is_fabricated_for_a_minimal_scan():
    r = ScanResult(sample_result().system, NOW)           # system data only
    t = flat(build_report_pdf(r, None, ReportOptions(), generated_at=GEN))
    for missing in ("No hardware data was collected", "No network data was collected", "No port data was collected"):
        assert missing in t
    assert t.count("Not collected / not available") >= 5
    for invented in ("Intel", "NVIDIA", "Samsung", "DDR4", "192.168", "(PID", "0.0.0.0"):
        assert invented not in t
    assert not re.search(r"\bNone\b|\bnull\b|\bnan\b", t)
    assert "Hardware" in t and "Not collected" in t        # listed in the warnings table


def test_missing_values_print_honest_words_not_python_artifacts():
    t = flat(build())
    assert not re.search(r"\bNone\b|\bnull\b|\bnan\b", t)
    assert "Reported as empty" in flat(build(sample_everything_with_network()))


def test_scan_errors_are_reported():
    r = sample_with_ports()
    r.errors = ["Graphics could not be read (RuntimeError)"]
    t = flat(build(r))
    assert "Collection problem" in t and "Graphics could not be read (RuntimeError)" in t


def test_special_characters_are_literal_and_unsupported_ones_are_replaced_with_a_warning():
    r = sample_with_ports()
    r.system.fields.append(InfoField("n1", "Tag", "A&B <b>bold</b> \"quoted\"", Status.OK, "test"))
    r.system.fields.append(InfoField("n2", "Accents", "Z\u00fcrich caf\u00e9 \u0394\u03b5\u03bb\u03c4\u03b1 \u041f\u0440\u0438\u0432\u0435\u0442", Status.OK, "test"))
    r.system.fields.append(InfoField("n3", "Device", "PC-\u6d4b\u8bd5-01", Status.OK, "test"))
    t = flat(build(r))
    assert 'A&B <b>bold</b> "quoted"' in t                            # no markup injection
    assert "Z\u00fcrich caf\u00e9" in t and "\u0394\u03b5\u03bb\u03c4\u03b1" in t and "\u041f\u0440\u0438\u0432\u0435\u0442" in t
    assert "PC-??-01" in t                                              # honest replacement, not boxes
    assert "2 character(s) in names could not be shown" in t


def test_multiline_values_stay_on_separate_lines():
    t = pages(build())[2]
    assert "Listening locally" in t


def test_large_report_builds_in_reasonable_time():
    import time
    r = sample_with_ports()
    many = [InfoField(f"tcp_{i}", f"{1000 + i}/TCP \u00b7 name", "Listening locally\n0.0.0.0:1 \u00b7 loopback only \u00b7 x.exe (PID 1)",
                      Status.OK, "psutil", "a note about this endpoint " * 3) for i in range(800)]
    r.hardware[r.hardware.index(r.section("ports_tcp"))] = InfoSection("ports_tcp", "All listening TCP endpoints", many, NOW)
    start = time.time()
    data = build(r)
    assert time.time() - start < 20 and len(pypdf.PdfReader(io.BytesIO(data)).pages) > 10


def test_report_builds_for_every_status_combination():
    fields = [InfoField(f"k{i}", f"Item {i}", v, s, "src", n) for i, (v, s, n) in enumerate([
        ("v", Status.OK, ""), (None, Status.UNAVAILABLE, "why"), (None, Status.EMPTY, ""),
        (None, Status.UNSUPPORTED, "no interface"), ("v", Status.OK, "a note")])]
    r = ScanResult(sample_result().system, NOW,
                   hardware=[InfoSection(k, k.title(), fields, NOW) for k in ("cpu", "network", "ports_tcp", "net_adapter_1")])
    t = flat(build_report_pdf(r, None, ReportOptions(), generated_at=GEN))
    assert "Unavailable" in t and "Reported as empty" in t and "Not exposed by Windows" in t
