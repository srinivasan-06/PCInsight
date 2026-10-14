from pathlib import Path

from pcinsight.core.paths import data_dir


def test_override_wins():
    assert data_dir({"PCINSIGHT_DATA_DIR": "X:/portable", "APPDATA": "C:/a"}, "nt", Path("C:/u")) == Path("X:/portable")


def test_windows_uses_appdata():
    assert data_dir({"APPDATA": "C:/Users/me/AppData/Roaming"}, "nt", Path("C:/Users/me")) == \
        Path("C:/Users/me/AppData/Roaming/PCInsight")


def test_windows_without_appdata_falls_back_to_home():
    assert data_dir({}, "nt", Path("C:/Users/me")) == Path("C:/Users/me/AppData/Roaming/PCInsight")


def test_linux_xdg_and_home():
    assert data_dir({"XDG_DATA_HOME": "/x"}, "posix", Path("/home/me")) == Path("/x/PCInsight")
    assert data_dir({}, "posix", Path("/home/me")) == Path("/home/me/.local/share/PCInsight")


def test_tests_are_isolated_from_the_real_folder(tmp_path):
    assert str(data_dir()).startswith(str(tmp_path))
