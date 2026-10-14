import errno
import os
from datetime import datetime

import pytest

from helpers import sample_with_ports
from pcinsight.report import ReportError, default_report_filename, writer, write_report


def leftovers(folder):
    return [p.name for p in folder.iterdir() if p.name.endswith(".tmp")]


def test_saves_a_valid_pdf_and_returns_the_path(tmp_path):
    out = write_report(str(tmp_path / "report.pdf"), sample_with_ports())
    assert out == str(tmp_path / "report.pdf")
    assert open(out, "rb").read(5) == b"%PDF-" and leftovers(tmp_path) == []


def test_pdf_extension_added_when_missing(tmp_path):
    assert write_report(str(tmp_path / "myreport"), sample_with_ports()).endswith("myreport.pdf")
    assert write_report(str(tmp_path / "other.PDF"), sample_with_ports()).endswith("other.PDF")


def test_unicode_path_and_spaces(tmp_path):
    folder = tmp_path / "Mein B\u00fcro \u2014 reports"
    folder.mkdir()
    assert os.path.exists(write_report(str(folder / "r\u00e9sum\u00e9 1.pdf"), sample_with_ports()))


def test_existing_file_is_replaced_atomically(tmp_path):
    target = tmp_path / "r.pdf"
    target.write_bytes(b"OLD")
    write_report(str(target), sample_with_ports())
    assert target.read_bytes().startswith(b"%PDF") and leftovers(tmp_path) == []


@pytest.mark.parametrize("path", ["", "   "])
def test_no_path_chosen(path):
    with pytest.raises(ReportError, match="No save location"):
        write_report(path, sample_with_ports())


def test_folder_given_instead_of_file(tmp_path):
    with pytest.raises(ReportError, match="is a folder"):
        write_report(str(tmp_path), sample_with_ports())


def test_missing_folder(tmp_path):
    with pytest.raises(ReportError, match="does not exist"):
        write_report(str(tmp_path / "nope" / "r.pdf"), sample_with_ports())


def test_permission_denied_or_file_open_in_viewer_keeps_original_and_cleans_up(tmp_path, monkeypatch):
    target = tmp_path / "r.pdf"
    target.write_bytes(b"OLD")

    def locked(src, dst):
        raise PermissionError(errno.EACCES, "locked")
    monkeypatch.setattr(writer.os, "replace", locked)
    with pytest.raises(ReportError, match="open in another program"):
        write_report(str(target), sample_with_ports())
    assert target.read_bytes() == b"OLD" and leftovers(tmp_path) == []


def test_permission_denied_when_creating_the_file(tmp_path, monkeypatch):
    real_open = open

    def deny(path, mode="r", *a, **k):
        if "w" in mode and str(path).endswith(".tmp"):
            raise PermissionError(errno.EACCES, "denied")
        return real_open(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", deny)
    with pytest.raises(ReportError, match="not allowed to save"):
        write_report(str(tmp_path / "r.pdf"), sample_with_ports())
    assert leftovers(tmp_path) == [] and not (tmp_path / "r.pdf").exists()


def test_disk_full(tmp_path, monkeypatch):
    def full(fd):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(writer.os, "fsync", full)
    with pytest.raises(ReportError, match="not enough free disk space"):
        write_report(str(tmp_path / "r.pdf"), sample_with_ports())
    assert leftovers(tmp_path) == [] and not (tmp_path / "r.pdf").exists()


def test_other_os_error_is_explained(tmp_path, monkeypatch):
    def broken(fd):
        raise OSError(errno.EIO, "I/O error")
    monkeypatch.setattr(writer.os, "fsync", broken)
    with pytest.raises(ReportError, match="could not be saved"):
        write_report(str(tmp_path / "r.pdf"), sample_with_ports())
    assert leftovers(tmp_path) == []


def test_invalid_or_too_long_name_never_crashes_or_leaves_files(tmp_path):
    with pytest.raises(ReportError):
        write_report(str(tmp_path / ("x" * 400 + ".pdf")), sample_with_ports())
    assert leftovers(tmp_path) == [] and list(tmp_path.iterdir()) == []


def test_generation_failure_saves_nothing_and_keeps_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "r.pdf"
    target.write_bytes(b"OLD")

    def boom(*a, **k):
        raise ValueError("secret-internal")
    monkeypatch.setattr(writer, "build_report_pdf", boom)
    with pytest.raises(ReportError, match="Nothing was saved") as e:
        write_report(str(target), sample_with_ports())
    assert "ValueError" in str(e.value) and "secret" not in str(e.value)
    assert target.read_bytes() == b"OLD" and leftovers(tmp_path) == []


def test_default_filename_has_no_personal_data():
    assert default_report_filename(datetime(2026, 10, 13, 9, 5)) == "PCInsight-Report-20261013-0905.pdf"
