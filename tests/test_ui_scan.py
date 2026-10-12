import threading

from PySide6.QtWidgets import QApplication

from helpers import sample_everything, sample_full_result, sample_result, wait_until
from pcinsight.ui.main_window import MainWindow


def make_window(qapp, fn):
    w = MainWindow(scan_fn=fn)
    w.show()
    qapp.processEvents()
    return w


def test_scan_populates_dashboard_and_hardware(qapp):
    w = make_window(qapp, lambda: sample_result())
    hw, dash = w.pages["Hardware"], w.pages["Dashboard"]
    assert not hw.has_data
    w.scan_bar.rescan_button.click()
    assert w.scan_bar.progress.isVisible() and not w.scan_bar.rescan_button.isEnabled()
    assert wait_until(qapp, lambda: hw.has_data)
    assert not w.scan_bar.progress.isVisible() and w.scan_bar.rescan_button.isEnabled()
    assert w.scan_bar.status_label.text() == "Last scan: 2026-10-12 12:00:00"
    assert w.scan_bar.rescan_button.text() == "Rescan"
    assert hw.table.value_labels["computer_name"].text() == "TEST-PC"
    assert "TEST-PC" in dash.system_card.summary_label.text()
    assert dash.system_card.status_label.text() == "Scanned"
    assert dash.cards[1].status_label.text() == "Not collected"  # sample has no hardware sections
    assert dash.cards[2].status_label.text() == "Not collected"
    assert "Module 5" in dash.cards[5].status_label.text()
    w.close()


def test_unavailable_and_empty_are_shown_honestly(qapp):
    w = make_window(qapp, lambda: sample_result(unavailable=True))
    w.scan_bar.rescan_button.click()
    hw = w.pages["Hardware"]
    assert wait_until(qapp, lambda: hw.has_data)
    assert hw.table.value_labels["manufacturer"].text() == "Unavailable"
    assert hw.table.value_labels["os_version"].text() == "Reported as empty"
    assert not hw.table.copy_buttons["manufacturer"].isEnabled()
    assert "2 unavailable" in w.pages["Dashboard"].system_card.status_label.text()
    w.close()


def test_copy_to_clipboard(qapp):
    w = make_window(qapp, lambda: sample_result())
    w.scan_bar.rescan_button.click()
    hw = w.pages["Hardware"]
    assert wait_until(qapp, lambda: hw.has_data)
    hw.table.copy_buttons["computer_name"].click()
    assert QApplication.clipboard().text() == "TEST-PC"
    assert hw.table.copy_buttons["computer_name"].text() == "Copied"
    w.close()


def test_long_device_name_is_not_truncated(qapp):
    w = make_window(qapp, lambda: sample_result(long_name=True))
    w.scan_bar.rescan_button.click()
    hw = w.pages["Hardware"]
    assert wait_until(qapp, lambda: hw.has_data)
    assert hw.table.value_labels["model"].text() == "Z" * 150
    assert hw.table.value_labels["model"].wordWrap()
    w.close()


def test_scan_failure_keeps_app_alive_and_allows_retry(qapp):
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("x")
        return sample_result()

    w = make_window(qapp, fn)
    w.scan_bar.rescan_button.click()
    assert wait_until(qapp, lambda: "failed" in w.scan_bar.status_label.text())
    assert w.scan_bar.rescan_button.isEnabled() and not w.scan_bar.progress.isVisible()
    assert w.pages["Dashboard"].system_card.status_label.text() == "Scan failed"
    w.scan_bar.rescan_button.click()
    assert wait_until(qapp, lambda: w.pages["Hardware"].has_data)
    w.close()


def test_repeated_rescans_do_not_stack_rows(qapp):
    w = make_window(qapp, lambda: sample_result())
    hw = w.pages["Hardware"]
    for i in range(3):
        w.scan_bar.rescan_button.click()
        assert wait_until(qapp, lambda: hw.has_data and w.scan_bar.rescan_button.isEnabled())
    qapp.processEvents()
    assert len(hw.table.value_labels) == 5
    w.close()


def test_close_window_during_scan(qapp):
    gate = threading.Event()
    w = make_window(qapp, lambda: gate.wait(0.3) or sample_result())
    w.scan_bar.rescan_button.click()
    w.close()
    qapp.processEvents()
    assert not w.controller.is_running


def test_hardware_sections_and_cpu_card(qapp):
    w = make_window(qapp, lambda: sample_full_result())
    w.scan_bar.rescan_button.click()
    hw, dash = w.pages["Hardware"], w.pages["Dashboard"]
    assert wait_until(qapp, lambda: hw.has_data)
    assert list(hw.tables) == ["system", "cpu", "motherboard", "bios"]
    assert hw.tables["cpu"].value_labels["cpu_name"].text() == "Test CPU 9000"
    chip = hw.tables["motherboard"]
    assert chip.value_labels["chipset"].text() == "Not exposed by Windows"
    assert not chip.copy_buttons["chipset"].isEnabled()
    assert hw.tables["bios"].value_labels["bios_version"].text() == "Unavailable"
    summary = dash.cards[1].summary_label.text()
    assert "Test CPU 9000" in summary and "8 cores / 16 threads" in summary and "Test Board" in summary
    assert dash.cards[1].status_label.text() == "Partial data (1 unavailable)"  # chipset not counted
    assert dash.cards[2].status_label.text() == "Not collected"
    w.close()


def test_scan_problems_shown_in_status_bar(qapp):
    def fn():
        r = sample_result()
        r.errors = ["CPU, motherboard and BIOS could not be read (RuntimeError)"]
        return r

    w = make_window(qapp, fn)
    w.scan_bar.rescan_button.click()
    assert wait_until(qapp, lambda: w.pages["Hardware"].has_data)
    text = w.scan_bar.status_label.text()
    assert "1 problem(s)" in text and "RuntimeError" in text
    w.close()


def test_rescan_replaces_sections_without_leftovers(qapp):
    w = make_window(qapp, lambda: sample_full_result())
    hw = w.pages["Hardware"]
    for _ in range(3):
        w.scan_bar.rescan_button.click()
        assert wait_until(qapp, lambda: hw.has_data and w.scan_bar.rescan_button.isEnabled())
    qapp.processEvents()
    assert list(hw.tables) == ["system", "cpu", "motherboard", "bios"]
    w.close()


def _scan_everything(qapp):
    w = make_window(qapp, lambda: sample_everything())
    w.scan_bar.rescan_button.click()
    assert wait_until(qapp, lambda: w.pages["Hardware"].has_data)
    return w


def test_memory_gpu_storage_cards_and_sections(qapp):
    w = _scan_everything(qapp)
    hw, dash = w.pages["Hardware"], w.pages["Dashboard"]
    assert list(hw.tables) == ["system", "cpu", "motherboard", "bios", "memory", "memory_module_1",
                               "gpu_1", "storage_disk_1", "volumes"]
    mem = dash.cards[2].summary_label.text()
    assert "31.9 GB usable (32 GB installed)" in mem and "2 of 4 slots populated" in mem and "DDR4" in mem
    assert dash.cards[2].status_label.text() == "Partial data (1 unavailable)"
    assert "Test GPU 3080" in dash.cards[3].summary_label.text()
    assert dash.cards[3].status_label.text() == "Scanned"
    st = dash.cards[4].summary_label.text()
    assert "Test SSD 970 (931.5 GB)" in st and "1 drive with free-space data" in st
    assert "Module 5" in dash.cards[5].status_label.text() and "Module 6" in dash.cards[6].status_label.text()
    w.close()


def test_filter_hides_nonmatching_rows_and_sections(qapp):
    w = _scan_everything(qapp)
    hw = w.pages["Hardware"]
    hw.filter_edit.setText("ddr4")
    qapp.processEvents()
    assert hw.tables["memory_module_1"].visible_keys() == ["type"]
    assert hw.tables["gpu_1"].visible_keys() == []
    assert hw.tables["gpu_1"].isHidden() and not hw.tables["memory_module_1"].isHidden()
    assert hw.no_match.isHidden()  # there are matches, so no 'no match' message
    hw.filter_edit.setText("zzz-nothing")
    qapp.processEvents()
    assert not hw.no_match.isHidden()
    hw.filter_edit.setText("")
    qapp.processEvents()
    assert hw.no_match.isHidden() and not hw.tables["gpu_1"].isHidden()
    assert len(hw.tables["gpu_1"].visible_keys()) == 2
    w.close()


def test_filter_survives_rescan(qapp):
    w = _scan_everything(qapp)
    hw = w.pages["Hardware"]
    hw.filter_edit.setText("gpu")
    w.scan_bar.rescan_button.click()
    assert wait_until(qapp, lambda: w.scan_bar.rescan_button.isEnabled())
    qapp.processEvents()
    assert hw.tables["gpu_1"].visible_keys() == ["gpu_name"]  # only the row whose text contains "gpu"
    assert hw.tables["storage_disk_1"].isHidden()
    w.close()
