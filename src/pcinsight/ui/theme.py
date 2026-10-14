"""Design tokens and stylesheet generation (light and dark)."""
from __future__ import annotations

LIGHT: dict[str, str] = {
    "bg": "#F3F5F9", "surface": "#FFFFFF", "border": "#D8DEE9",
    "text": "#111827", "muted": "#4B5563", "accent": "#2563EB",
    "accent_text": "#FFFFFF", "ok": "#166534", "danger": "#B91C1C", "sidebar": "#111827", "sidebar_text": "#D1D9E6",
    "sidebar_hover": "#1B2538", "sidebar_active": "#26345A", "badge_bg": "#E5EAF3",
}
DARK: dict[str, str] = {
    "bg": "#0F172A", "surface": "#1E293B", "border": "#334155",
    "text": "#F1F5F9", "muted": "#AAB7CA", "accent": "#60A5FA",
    "accent_text": "#0B1220", "ok": "#4ADE80", "danger": "#F87171", "sidebar": "#0A0F1C", "sidebar_text": "#CBD5E1",
    "sidebar_hover": "#141C30", "sidebar_active": "#22304F", "badge_bg": "#2B3A52",
}
THEMES = {"light": LIGHT, "dark": DARK}


def build_stylesheet(t: dict[str, str]) -> str:
    return f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; }}
QMainWindow, #Root, #Content, QScrollArea, #ScrollInner {{ background: {t['bg']}; border: none; }}
QLabel {{ color: {t['text']}; background: transparent; }}
QLabel#Muted {{ color: {t['muted']}; }}
QLabel#PageTitle {{ font-size: 20pt; font-weight: 600; }}
QLabel#CardTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#EmptyTitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#Badge {{ background: {t['badge_bg']}; color: {t['text']}; border-radius: 8px; padding: 2px 10px; font-size: 9pt; }}

#Sidebar {{ background: {t['sidebar']}; }}
#Sidebar QLabel#Brand {{ color: #FFFFFF; font-size: 15pt; font-weight: 700; }}
#Sidebar QLabel#BrandSub {{ color: {t['sidebar_text']}; font-size: 8pt; }}
QPushButton#NavButton {{ color: {t['sidebar_text']}; background: transparent; text-align: left;
    padding: 10px 16px; border: none; border-left: 3px solid transparent; border-radius: 0; }}
QPushButton#NavButton:hover {{ background: {t['sidebar_hover']}; }}
QPushButton#NavButton:checked {{ background: {t['sidebar_active']}; color: #FFFFFF;
    border-left: 3px solid {t['accent']}; font-weight: 600; }}
QPushButton#NavButton:focus {{ outline: none; border: 1px solid {t['accent']}; }}
QPushButton#ThemeButton {{ color: {t['sidebar_text']}; background: transparent;
    border: 1px solid {t['sidebar_active']}; border-radius: 6px; padding: 6px 10px; }}
QPushButton#ThemeButton:hover {{ background: {t['sidebar_hover']}; }}

#Card, #EmptyPanel, #ScanBar {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
QPushButton#Primary {{ background: {t['accent']}; color: {t['accent_text']}; border: none;
    border-radius: 6px; padding: 7px 16px; font-weight: 600; }}
QCheckBox, QComboBox {{ color: {t['text']}; }}
QComboBox {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 5px 8px; }}
QPushButton#Primary:disabled {{ background: {t['badge_bg']}; color: {t['muted']}; }}
QProgressBar {{ background: {t['badge_bg']}; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 4px; }}
QLabel#SectionTitle {{ font-size: 12pt; font-weight: 600; }}
QLabel#FieldLabel {{ color: {t['muted']}; font-weight: 600; }}
QLabel#ValueMissing {{ color: {t['muted']}; font-style: italic; }}
QLabel#Success {{ color: {t['ok']}; font-weight: 600; }}
QLabel#Error {{ color: {t['danger']}; font-weight: 600; }}
QLabel#Detail {{ color: {t['muted']}; font-size: 8.5pt; }}
QLabel#Summary {{ font-size: 10pt; }}
QPushButton#Ghost {{ background: transparent; color: {t['accent']}; border: 1px solid {t['border']};
    border-radius: 6px; padding: 4px 12px; }}
QPushButton#Ghost:hover {{ background: {t['badge_bg']}; }}
QPushButton#Ghost:disabled {{ color: {t['muted']}; }}
QLineEdit#Search {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
    border-radius: 6px; padding: 7px 10px; }}
QLineEdit#Search:focus {{ border: 1px solid {t['accent']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
