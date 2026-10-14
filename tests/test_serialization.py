import json
from datetime import datetime

import pytest

from helpers import NOW, sample_everything_with_network, sample_result, sample_with_ports
from pcinsight.core.models import InfoField, InfoSection, Status
from pcinsight.core.scan import ScanResult
from pcinsight.core.serialization import SCHEMA, result_from_dict, result_to_dict


def test_round_trip_is_exact_for_a_rich_result():
    r = sample_with_ports()
    r.errors = ["Graphics could not be read (RuntimeError)"]
    back = result_from_dict(json.loads(json.dumps(result_to_dict(r))))
    assert back == r and back.gateways == ["192.168.1.1"]
    assert [s.key for s in back.network_sections()] == [s.key for s in r.network_sections()]


def test_all_statuses_unicode_and_none_values_survive():
    fields = [InfoField("a", "\u00dcmlaut \u6d4b\u8bd5", "val \"q\" <x> \n line2", Status.OK, "s", "n"),
              InfoField("b", "b", None, Status.UNAVAILABLE, "s", "why"), InfoField("c", "c", None, Status.EMPTY, "s"),
              InfoField("d", "d", None, Status.UNSUPPORTED, "s", "no interface")]
    r = ScanResult(sample_result().system, NOW, hardware=[InfoSection("cpu", "CPU", fields, NOW, "note")])
    assert result_from_dict(json.loads(json.dumps(result_to_dict(r), ensure_ascii=False))) == r


def test_payload_is_plain_json_with_schema():
    d = result_to_dict(sample_result())
    assert d["schema"] == SCHEMA and json.dumps(d)


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("system"), lambda d: d.update(system=[]), lambda d: d.update(scanned_at="yesterday"),
    lambda d: d.update(scanned_at=5), lambda d: d.update(hardware="x"), lambda d: d.update(hardware=[5]),
    lambda d: d["system"]["fields"].append({"key": "k"}),
    lambda d: d["system"]["fields"][0].update(status="mystery"),
    lambda d: d["system"]["fields"][0].update(label=None),
    lambda d: d["system"]["fields"][0].update(value=5),
    lambda d: d.update(errors=[1]), lambda d: d.update(schema="1"), lambda d: d.update(schema=0),
    lambda d: d["system"].update(collected_at="nope"),
])
def test_damaged_payloads_raise_value_error(mutate):
    d = result_to_dict(sample_everything_with_network())
    mutate(d)
    with pytest.raises(ValueError):
        result_from_dict(d)


def test_newer_schema_is_refused_clearly():
    d = result_to_dict(sample_result())
    d["schema"] = SCHEMA + 1
    with pytest.raises(ValueError, match="newer version"):
        result_from_dict(d)


@pytest.mark.parametrize("junk", [None, [], "x", 5])
def test_non_objects_rejected(junk):
    with pytest.raises(ValueError):
        result_from_dict(junk)
