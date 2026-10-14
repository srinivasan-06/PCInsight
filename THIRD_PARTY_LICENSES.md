# Third-party licenses (PRELIMINARY - verify before any release)
| Package | Purpose | License (to verify) | Notes |
|---|---|---|---|
| PySide6 (Qt for Python) | UI | LGPLv3 / GPL / commercial | Commercial closed-source use is generally possible under LGPL with obligations (e.g. dynamic linking, notices, allow relinking). Review at Module 10. |
| psutil | boot time (and later CPU/memory/network/ports) | BSD-3-Clause | Permissive; keep the copyright notice in distributions. |
| ReportLab | PDF generation | BSD-3-Clause (open-source toolkit; the separate paid ReportLab PLUS is not used) | Verify at Module 10. Keep notice. |
| Pillow (ReportLab dependency) | image support inside ReportLab | HPND (permissive) | Verify at Module 10. |
| charset-normalizer (ReportLab dependency) | text encoding | MIT | |
| DejaVu Sans fonts (bundled, src/pcinsight/assets/fonts) | report text | Bitstream Vera licence + public-domain DejaVu changes | Explicitly allows selling as part of a larger package; the licence text ships in assets/fonts/LICENSE_DEJAVU.txt and must be kept. Fonts may not be sold by themselves or modified under the Vera/Bitstream names. |
| pypdf (dev only) | tests read the generated PDFs | BSD-3-Clause | Not shipped. |
| pytest (dev only) | tests | MIT | Not shipped. |
