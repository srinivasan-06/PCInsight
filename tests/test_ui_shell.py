from PySide6.QtWidgets import QLabel

EXPECTED = ["Dashboard", "Hardware", "Network", "Port Analyzer", "Reports", "Settings", "About"]


def test_nav_order_and_labels(window):
    assert [b.text() for b in window.nav_buttons] == EXPECTED


def test_every_nav_item_opens_its_page(window, qapp):
    for i, name in enumerate(EXPECTED):
        window.nav_buttons[i].click()
        qapp.processEvents()
        assert window.stack.currentWidget() is window.pages[name]
        assert window.nav_buttons[i].isChecked()


def test_resize_and_reflow(window, qapp):
    dash = window.pages["Dashboard"]
    window.resize(1500, 800); qapp.processEvents()
    wide = dash.grid.columns
    window.resize(830, 600); qapp.processEvents()
    narrow = dash.grid.columns
    assert wide > narrow >= 1


def test_theme_toggle(window):
    assert window.theme_name == "light"
    window.toggle_theme()
    assert window.theme_name == "dark"
    window.toggle_theme()
    assert window.theme_name == "light"


def test_no_fabricated_data(window):
    dash = window.pages["Dashboard"]
    assert len(dash.cards) == 7
    assert all(c.status_label.text() == "Not scanned yet" for c in dash.cards)
    assert window.scan_bar.status_label.text() == "Last scan: never"
    assert window.scan_bar.rescan_button.isEnabled()  # Module 2: scanning is available
    assert not window.scan_bar.progress.isVisible()


def test_about_shows_real_runtime_info(window):
    texts = " ".join(l.text() for l in window.pages["About"].findChildren(QLabel))
    assert "PCInsight 0.1.0" in texts and "PySide6" in texts
