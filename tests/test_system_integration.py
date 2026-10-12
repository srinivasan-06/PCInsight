"""Real-machine checks. Windows only. Run with: python -m pytest tests/test_system_integration.py -s"""
import os
import re
import sys

import pytest

from pcinsight.core.models import Status
from pcinsight.core.system_info import collect_system_overview

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only integration test")


@pytest.fixture(scope="module")
def overview():
    ov = collect_system_overview()
    for f in ov.fields:
        print(f"{f.label:22} {f.status.value:12} {f.value or f.note}")
    return ov


def test_core_fields_present(overview):
    for key in ("computer_name", "os_edition", "os_build", "architecture", "last_boot", "uptime"):
        assert overview.get(key).status is Status.OK, key


def test_values_match_the_machine(overview):
    assert overview.get("computer_name").value.lower() == os.environ["COMPUTERNAME"].lower()
    assert re.match(r"^\d{5}(\.\d+)?$", overview.get("os_build").value)
    assert overview.get("os_edition").value.startswith("Windows")
