import logging

from pcinsight.core import diagnostics as dg


def test_enable_writes_a_log_and_disable_stops_it(tmp_path):
    dg.configure_logging(True, tmp_path / "logs")
    logging.getLogger("pcinsight.test").warning("something failed (ValueError)")
    text = (tmp_path / "logs" / "pcinsight.log").read_text()
    assert "Diagnostic logging enabled" in text and "something failed (ValueError)" in text
    dg.configure_logging(False, None)
    logging.getLogger("pcinsight.test").warning("after disable")
    assert "after disable" not in (tmp_path / "logs" / "pcinsight.log").read_text()


def test_enabling_twice_does_not_duplicate_lines(tmp_path):
    dg.configure_logging(True, tmp_path / "logs")
    dg.configure_logging(True, tmp_path / "logs")
    logging.getLogger("pcinsight.test").warning("only-once-marker")
    assert (tmp_path / "logs" / "pcinsight.log").read_text().count("only-once-marker") == 1


def test_log_files_can_be_deleted_even_while_logging_is_on(tmp_path):
    d = tmp_path / "logs"
    dg.configure_logging(True, d)
    assert dg.delete_log_files(d) >= 1
    logging.getLogger("pcinsight.test").warning("still logging")
    assert "still logging" in (d / "pcinsight.log").read_text()      # logging resumed in a fresh file
    dg.configure_logging(False, None)
    assert dg.delete_log_files(d) == 1 and dg.log_files(d) == []


def test_no_folder_no_crash(tmp_path):
    assert dg.log_files(tmp_path / "missing") == [] and dg.delete_log_files(tmp_path / "missing") == 0
    dg.configure_logging(False, None)


def test_the_log_contains_no_addresses_from_a_failed_scan(tmp_path):
    from helpers import make_net_sources
    from pcinsight.core.common import CollectionError
    from pcinsight.core.network_info import collect_network
    d = tmp_path / "logs"
    dg.configure_logging(True, d)
    collect_network(make_net_sources(ps_error=CollectionError("PowerShell was not found")))
    collect_network(make_net_sources(ps=[{"adapters": "bad"}]))
    dg.configure_logging(False, None)
    text = (d / "pcinsight.log").read_text()
    for secret in ("192.168.1.20", "AA-BB-CC-DD-EE-FF", "2001:db8"):
        assert secret not in text
