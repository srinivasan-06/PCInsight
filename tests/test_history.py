import sqlite3
import time
import zlib
from datetime import datetime, timedelta

import pytest

from helpers import sample_everything_with_network, sample_result, sample_with_ports
from pcinsight.core.history import HistoryError, HistoryStore
from pcinsight.core.models import InfoField, InfoSection, Status
from pcinsight.core.scan import ScanResult


def store(tmp_path):
    return HistoryStore(tmp_path / "history.sqlite3")


def at(result, when):
    return ScanResult(result.system, when, hardware=result.hardware, errors=result.errors, gateways=result.gateways)


def test_save_list_and_load_round_trip(tmp_path):
    h = store(tmp_path)
    r = sample_with_ports()
    sid = h.save(r, "0.1.0")
    entries = h.list()
    assert len(entries) == 1 and entries[0].id == sid and entries[0].computer == "TEST-PC"
    assert entries[0].scanned_at == r.scanned_at and entries[0].size_bytes > 100
    assert h.load(sid) == r


def test_problem_count_includes_unavailable_fields_and_errors(tmp_path):
    h = store(tmp_path)
    r = sample_with_ports()
    r.errors = ["Graphics could not be read (RuntimeError)"]
    h.save(r)
    expected = (r.system.unavailable_count + sum(s.unavailable_count for s in r.hardware) + 1)
    assert h.list()[0].problems == expected and expected >= 2


def test_newest_first(tmp_path):
    h = store(tmp_path)
    base = datetime(2026, 10, 1, 12, 0, 0)
    for i in (2, 0, 1):
        h.save(at(sample_result(), base + timedelta(days=i)))
    assert [e.scanned_at.day for e in h.list()] == [3, 2, 1]


def test_computer_name_blank_when_unavailable(tmp_path):
    h = store(tmp_path)
    r = sample_result()
    r.system.fields[0] = InfoField("computer_name", "Computer name", None, Status.UNAVAILABLE, "t", "x")
    h.save(r)
    assert h.list()[0].computer == ""


def test_delete_some(tmp_path):
    h = store(tmp_path)
    ids = [h.save(sample_result()) for _ in range(4)]
    assert h.delete(ids[:2]) == 2 and h.delete([]) == 0 and h.delete([9999]) == 0
    assert sorted(e.id for e in h.list()) == sorted(ids[2:])


def test_delete_all_empties_and_compacts_the_file(tmp_path):
    h = store(tmp_path)
    big = sample_everything_with_network()
    big.hardware.append(InfoSection("x", "X", [InfoField(f"k{i}", f"L{i}", "v" * 400 + str(i), Status.OK, "s")
                                               for i in range(600)], big.scanned_at))
    for _ in range(5):
        h.save(big)
    before = h.path.stat().st_size
    assert h.delete_all() == 5 and h.list() == []
    after = h.path.stat().st_size
    assert after < before / 2 and h.stats() == (0, after)


def test_secure_delete_is_enabled(tmp_path):
    h = store(tmp_path)
    conn = h._open()
    try:
        assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
    finally:
        conn.close()


def test_deleted_scan_text_is_not_left_in_the_file(tmp_path):
    h = store(tmp_path)
    marker = "UNIQUE-MARKER-9f3a1c"
    r = sample_result()
    r.system.fields.append(InfoField("m", "Marker", marker, Status.OK, "s"))
    sid = h.save(r)
    conn = sqlite3.connect(h.path)           # prove the stored value is findable before deletion (decompressed)
    assert marker.encode() in zlib.decompress(conn.execute("SELECT payload FROM scans").fetchone()[0])
    conn.close()
    h.delete([sid])
    h.delete_all()
    assert marker.encode() not in h.path.read_bytes()


def test_retention_by_days(tmp_path):
    h = store(tmp_path)
    now = datetime(2026, 10, 14, 12, 0, 0)
    for days_old in (1, 10, 40, 100, 400):
        h.save(at(sample_result(), now - timedelta(days=days_old)))
    assert h.apply_retention(90, 0, now) == 2
    assert [e.scanned_at for e in h.list()] == [now - timedelta(days=1), now - timedelta(days=10), now - timedelta(days=40)]


def test_retention_by_count_keeps_the_newest(tmp_path):
    h = store(tmp_path)
    base = datetime(2026, 10, 1)
    for i in range(10):
        h.save(at(sample_result(), base + timedelta(hours=i)))
    assert h.apply_retention(0, 3) == 7
    assert [e.scanned_at.hour for e in h.list()] == [9, 8, 7]


def test_retention_forever_and_combined(tmp_path):
    h = store(tmp_path)
    now = datetime(2026, 10, 14)
    for i in range(6):
        h.save(at(sample_result(), now - timedelta(days=i * 100)))
    assert h.apply_retention(0, 100, now) == 0 and len(h.list()) == 6      # forever + roomy limit: nothing removed
    assert h.apply_retention(250, 2, now) == 4 and len(h.list()) == 2


def test_stats(tmp_path):
    h = store(tmp_path)
    assert h.stats()[0] == 0
    h.save(sample_result())
    count, size = h.stats()
    assert count == 1 and size > 0


def test_unknown_scan_id(tmp_path):
    with pytest.raises(HistoryError, match="no longer exists"):
        store(tmp_path).load(123)


def test_damaged_database_is_set_aside_and_replaced(tmp_path):
    p = tmp_path / "history.sqlite3"
    p.write_bytes(b"this is definitely not a sqlite database" * 50)
    h = HistoryStore(p)
    assert h.list() == [] and "damaged" in h.recovery_message
    assert any(f.name.startswith("history.sqlite3.damaged-") for f in tmp_path.iterdir())
    h.save(sample_result())
    assert len(h.list()) == 1


def test_one_damaged_scan_does_not_break_the_others(tmp_path):
    h = store(tmp_path)
    good, bad = h.save(sample_result()), h.save(sample_result())
    conn = sqlite3.connect(h.path)
    conn.execute("UPDATE scans SET payload=? WHERE id=?", (b"garbage", bad))
    conn.commit()
    conn.close()
    assert len(h.list()) == 2 and h.load(good)
    with pytest.raises(HistoryError, match="damaged"):
        h.load(bad)


def test_valid_compression_but_wrong_content(tmp_path):
    h = store(tmp_path)
    sid = h.save(sample_result())
    conn = sqlite3.connect(h.path)
    conn.execute("UPDATE scans SET payload=? WHERE id=?", (zlib.compress(b'{"schema": 1}'), sid))
    conn.commit()
    conn.close()
    with pytest.raises(HistoryError, match="damaged"):
        h.load(sid)


def test_scan_from_a_newer_version_is_refused(tmp_path):
    import json
    from pcinsight.core.serialization import result_to_dict
    h = store(tmp_path)
    sid = h.save(sample_result())
    d = result_to_dict(sample_result())
    d["schema"] = 99
    conn = sqlite3.connect(h.path)
    conn.execute("UPDATE scans SET payload=? WHERE id=?", (zlib.compress(json.dumps(d).encode()), sid))
    conn.commit()
    conn.close()
    with pytest.raises(HistoryError, match="newer version"):
        h.load(sid)


def test_database_from_a_newer_version_is_refused(tmp_path):
    p = tmp_path / "history.sqlite3"
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA user_version=42")
    conn.commit()
    conn.close()
    with pytest.raises(HistoryError, match="newer version"):
        HistoryStore(p).list()
    assert p.exists() and not any("damaged" in f.name for f in tmp_path.iterdir())   # never destroyed


def test_locked_database_is_reported_not_crashed(tmp_path, monkeypatch):
    h = store(tmp_path)
    h.save(sample_result())
    real = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda path, timeout=5.0: real(path, timeout=0.05))
    blocker = real(h.path)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(HistoryError, match="busy"):
            h.save(sample_result())
    finally:
        blocker.rollback()
        blocker.close()
    monkeypatch.undo()
    assert len(h.list()) == 1                          # nothing half-written


def test_path_that_is_a_folder_is_reported(tmp_path):
    (tmp_path / "history.sqlite3").mkdir()
    with pytest.raises(HistoryError):
        store(tmp_path).list()


def test_folder_is_created_on_demand(tmp_path):
    h = HistoryStore(tmp_path / "deep" / "er" / "h.sqlite3")
    h.save(sample_result())
    assert h.path.exists()


def test_many_scans_stay_fast(tmp_path):
    h = store(tmp_path)
    r = sample_everything_with_network()
    start = time.time()
    for i in range(150):
        h.save(at(r, datetime(2026, 1, 1) + timedelta(hours=i)))
    assert len(h.list()) == 150 and time.time() - start < 15
    assert h.apply_retention(0, 20) == 130 and len(h.list()) == 20


def test_unserialisable_result_is_a_clean_error(tmp_path):
    r = sample_result()
    r.errors = [object()]  # type: ignore[list-item]
    with pytest.raises(HistoryError, match="could not be prepared"):
        store(tmp_path).save(r)
