from collections import Counter
from xml.etree import ElementTree as ET

import pytest

from benchmarks.replay import assess, narrow_system_edges, note_key
from src.studio.document import new_score, replace_bar
from src.studio.scan_options import _proven_choir_layout


def two_labels():
    root = ET.Element("book")
    score = ET.SubElement(root, "score")
    page = ET.SubElement(ET.SubElement(root, "sheet"), "page")
    for j, names in enumerate([["Soprano", "Alto", "Tenor", "Bass"], ["S.", "A.", "T.", "B."]]):
        system = ET.SubElement(page, "system")
        for i, name in enumerate(names):
            pid = str(1+i+4*j)
            part = ET.SubElement(system, "part", {"logical-id": pid, "name": name})
            logical = ET.SubElement(score, "logical-part", {"id": pid, "staff-count": "1", "name": name})
            for element in [part, logical]:
                ET.SubElement(element, "staff-configuration", {"line-count": "5"})
    return root


def test_named_aliases_require_consistent_assignments():
    root = two_labels()
    assert _proven_choir_layout(root) == "satb"
    rows = root.findall("sheet/page/system")
    rows[1][0].set("logical-id", "2")
    assert _proven_choir_layout(root) is None


@pytest.mark.parametrize("location,attribute,value", [
    ("score", "logicals-locked", "true"), ("sheet/page/system/part", "manual", "true"),
    ("score/logical-part", "midi-program", "18"), ("sheet/page/system/part", "name", "Solo"),
])
def test_manual_or_conflicting_ensemble_declines(location, attribute, value):
    root = two_labels()
    root.find(location).set(attribute, value)
    assert _proven_choir_layout(root) is None


def test_saved_scan_scoring_and_missing_silent_bar():
    xml = replace_bar(new_score(template="melody", bars=1), 0, 0, "C4/q D4/q E4/h")
    truth = Counter([note_key(0, "C4", 1), note_key(1, "D4", 1), note_key(2, "F4", 2)])
    bars = {(0, 1): truth, (0, 2): Counter()}
    row, diff = assess(xml, {"expectedParts": ["Voice"]}, bars)
    assert row["noteComparison"] == dict(referencePartBars=2, exactPartBars=0, absentPartBars=1,
                                         matched=2, missing=1, extra=1)
    assert diff[0, 2][2]
    row, _ = assess(xml, {"expectedParts": ["I", "II", "Piano"]}, bars)
    assert row["noteComparison"] is None


def test_narrow_system_edge_is_a_location_even_when_stack_ids_repeat():
    system = ET.fromstring('<system id="2"><stack id="1" left="10" right="110"/>'
                           '<stack id="2" left="110" right="210"/>'
                           '<stack id="2" left="210" right="218" special="CAUTIONARY" duration="0"/></system>')
    assert narrow_system_edges(system, 5) == [
        dict(page=5, systemId="2", edge="last", stackId="2", relativeWidth=0.08,
             engineSpecial="CAUTIONARY", duration="0", expected=None, excess=None)]
    system[-1].set("right", "235")
    assert narrow_system_edges(system, 5) == []
    system.remove(system[0])
    assert narrow_system_edges(system, 5) == []
