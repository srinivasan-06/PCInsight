"""PDF report generation. Knows nothing about scanning: it only formats a finished ScanResult."""
from .pdf_report import ReportOptions, build_report_pdf
from .writer import ReportError, default_report_filename, write_report

__all__ = ["ReportOptions", "build_report_pdf", "ReportError", "write_report", "default_report_filename"]
