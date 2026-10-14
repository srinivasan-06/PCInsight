"""Report fonts. DejaVu Sans is bundled (free licence, may be sold as part of a larger package) so reports
look the same on every PC and cover accented Latin, Greek and Cyrillic. Characters the font lacks (for
example Chinese or Kannada device names) are replaced with '?' and counted, never drawn as broken boxes."""
from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
REGULAR, BOLD, ITALIC = "PCI-Sans", "PCI-Sans-Bold", "PCI-Sans-Italic"
_registered = False


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    for name, file in ((REGULAR, "DejaVuSans.ttf"), (BOLD, "DejaVuSans-Bold.ttf"), (ITALIC, "DejaVuSans-Oblique.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    pdfmetrics.registerFontFamily(REGULAR, normal=REGULAR, bold=BOLD, italic=ITALIC, boldItalic=BOLD)
    _registered = True


class TextSanitizer:
    """Makes text safe for the report font and counts what had to be replaced."""

    def __init__(self) -> None:
        register_fonts()
        self._glyphs = pdfmetrics.getFont(REGULAR).face.charToGlyph
        self.replaced = 0

    def clean(self, text: object) -> str:
        out = []
        for ch in "" if text is None else str(text):
            if ch in "\n\t" or ord(ch) in self._glyphs:
                out.append(ch)
            elif ch == "\r":
                continue
            else:
                out.append("?")
                self.replaced += 1
        return "".join(out)
