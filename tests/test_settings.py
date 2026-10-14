import json
import os

import pytest

from pcinsight.core import settings as st
from pcinsight.core.ports_info import DEFAULT_IMPORTANT_PORTS
from pcinsight.core.settings import Settings, SettingsError, SettingsStore, parse_port_list, validate


def store(tmp_path):
    return SettingsStore(tmp_path / "settings.json")


def test_defaults_when_no_file_exists(tmp_path):
    s = store(tmp_path)
    assert s.settings == Settings() and s.load_warning == "" and not s.path.exists()
    assert s.settings.theme == "light" and s.settings.paper == "A4" and s.settings.history_enabled
    assert s.settings.important_ports == tuple(DEFAULT_IMPORTANT_PORTS) and not s.settings.diagnostic_logging
    assert s.settings.retention_days == 90 and s.settings.retention_max_scans == 50


def test_changes_are_saved_and_survive_a_restart(tmp_path):
    s = store(tmp_path)
    assert s.update(theme="dark", paper="Letter", important_ports=[22, 8080], history_enabled=False,
                    retention_days=30, retention_max_scans=25, diagnostic_logging=True,
                    report_include_ports=False)
    again = store(tmp_path).settings
    assert again.theme == "dark" and again.paper == "Letter" and again.important_ports == (22, 8080)
    assert not again.history_enabled and again.retention_days == 30 and again.retention_max_scans == 25
    assert again.diagnostic_logging and not again.report_include_ports and again.report_include_network
    raw = json.loads(s.path.read_text())
    assert raw["important_ports"] == [22, 8080] and raw["schema"] == 1


def test_no_temporary_files_left_behind(tmp_path):
    s = store(tmp_path)
    s.update(theme="dark")
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


def test_invalid_values_are_replaced_one_by_one():
    s, notes = validate({"theme": "neon", "paper": "A4", "retention_days": -5, "retention_max_scans": 99999,
                         "history_enabled": "yes", "important_ports": [22, 22], "diagnostic_logging": True,
                         "report_include_ports": 1})
    assert s.theme == "light" and s.paper == "A4" and s.retention_days == 90 and s.retention_max_scans == 50
    assert s.history_enabled is True and s.important_ports == tuple(DEFAULT_IMPORTANT_PORTS)
    assert s.diagnostic_logging is True and s.report_include_ports is True
    assert len(notes) == 6


def test_unknown_keys_ignored_and_missing_keys_default():
    s, notes = validate({"theme": "dark", "from_the_future": 1})
    assert s.theme == "dark" and s.paper == "A4" and notes == []


def test_empty_port_list_is_a_valid_choice():
    s, notes = validate({"important_ports": []})
    assert s.important_ports == () and notes == []


@pytest.mark.parametrize("bad", [[0], [70000], ["22"], [True], [1.5], "22", 5, [22] * 3, list(range(1, 202))])
def test_invalid_port_lists_reset(bad):
    s, notes = validate({"important_ports": bad})
    assert s.important_ports == tuple(DEFAULT_IMPORTANT_PORTS) and notes


@pytest.mark.parametrize("content", ["{not json", "", "[1,2,3]", "null", "\x00\x01 binary", '"just a string"'])
def test_damaged_file_gives_defaults_and_is_kept_aside(tmp_path, content):
    p = tmp_path / "settings.json"
    p.write_text(content, encoding="utf-8")
    s = SettingsStore(p)
    assert s.settings == Settings()
    assert s.load_warning
    if content.strip() in ("[1,2,3]", "null", '"just a string"'):
        assert "settings object" in s.load_warning or "invalid" in s.load_warning.lower() or "damaged" in s.load_warning.lower()
    else:
        assert "damaged" in s.load_warning and not p.exists()
        assert any(f.name.startswith("settings.json.damaged-") for f in tmp_path.iterdir())


def test_undecodable_bytes(tmp_path):
    p = tmp_path / "settings.json"
    p.write_bytes(b"\xff\xfe\x00bad")
    s = SettingsStore(p)
    assert s.settings == Settings() and "damaged" in s.load_warning


def test_partly_valid_file_keeps_the_good_values(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"theme": "dark", "paper": "Tabloid"}))
    s = SettingsStore(p)
    assert s.settings.theme == "dark" and s.settings.paper == "A4"
    assert "paper" in s.load_warning


def test_byte_order_mark_tolerated(tmp_path):
    p = tmp_path / "settings.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"theme": "dark"}).encode())
    assert SettingsStore(p).settings.theme == "dark"


def test_unreadable_file_is_reported(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text("{}")
    real = type(p).read_text

    def deny(self, *a, **k):
        raise PermissionError("denied")
    monkeypatch.setattr(type(p), "read_text", deny)
    s = SettingsStore(p)
    monkeypatch.setattr(type(p), "read_text", real)
    assert s.settings == Settings() and "could not be read" in s.load_warning and p.exists()


def test_save_failure_is_explained_and_the_change_stays_active(tmp_path, monkeypatch):
    s = store(tmp_path)

    def locked(src, dst):
        raise PermissionError("locked")
    monkeypatch.setattr(st.os, "replace", locked)
    assert s.update(theme="dark") is False
    assert s.settings.theme == "dark"                          # still active in this session
    assert "not allowed" in s.last_error and "until you close PCInsight" in s.last_error
    assert not any(f.name.endswith(".tmp") for f in tmp_path.iterdir())


def test_other_save_errors(tmp_path, monkeypatch):
    s = store(tmp_path)
    monkeypatch.setattr(st.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(28, "No space")))
    assert s.update(theme="dark") is False and "could not be written" in s.last_error


def test_update_validates_input(tmp_path):
    s = store(tmp_path)
    s.update(theme="neon", retention_days="abc", important_ports=[70000])
    assert s.settings.theme == "light" and s.settings.retention_days == 90
    assert s.settings.important_ports == tuple(DEFAULT_IMPORTANT_PORTS)


def test_reset_restores_defaults_and_saves(tmp_path):
    s = store(tmp_path)
    s.update(theme="dark", important_ports=[1])
    assert s.reset() and store(tmp_path).settings == Settings()


def test_save_creates_missing_folders(tmp_path):
    s = SettingsStore(tmp_path / "a" / "b" / "settings.json")
    assert s.update(theme="dark") and (tmp_path / "a" / "b" / "settings.json").exists()


@pytest.mark.parametrize("text,ports,errors,warnings", [
    ("22, 80 443;8080", [22, 80, 443, 8080], 0, 0),
    ("", [], 0, 0), ("   ", [], 0, 0),
    ("22,22,80", [22, 80], 0, 1),
    ("abc, 22", [22], 1, 0), ("0 65536 -1", [], 3, 0), ("65535 1", [65535, 1], 0, 0),
    ("1e3 2.5 0x50", [], 3, 0), ("\u0663\u0664", [], 1, 0)])
def test_parse_port_list(text, ports, errors, warnings):
    p, e, w = parse_port_list(text)
    assert (p, len(e), len(w)) == (ports, errors, warnings)


def test_parse_port_list_limit_and_messages():
    p, e, _ = parse_port_list(" ".join(str(i) for i in range(1, 250)))
    assert any("At most 200" in x for x in e)
    _, e, _ = parse_port_list("70000 abc")
    assert "70000 is outside the valid range 1-65535" in e and "\"abc\" is not a port number" in e
