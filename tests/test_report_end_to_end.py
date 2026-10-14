"""Real scan -> real PDF. Runs on any OS (the scan itself adapts to what the machine can provide)."""
import os
import re
import shutil

import pypdf

from pcinsight.core.models import Status
from pcinsight.core.scan import run_scan
from pcinsight.report import write_report


def test_real_scan_to_pdf_report(tmp_path):
    result = run_scan()
    out = write_report(str(tmp_path / "real-report.pdf"), result)
    reader = pypdf.PdfReader(out)
    text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in reader.pages))
    print(f"\nReport pages: {len(reader.pages)}, size: {len(open(out, 'rb').read()) // 1024} KB")
    name = result.system.get("computer_name")
    assert name.status is Status.OK and name.value in text
    assert "Page 1 of" in text and "6. About this scan and its limitations" in text
    for sec in result.hardware:
        assert sec.title in text, sec.title
    keep = os.environ.get("PCINSIGHT_KEEP_REPORT")
    if keep:                                   # optional: set this variable to keep a copy for viewing
        shutil.copy(out, keep)
