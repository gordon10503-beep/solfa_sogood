"""Review a temporary key disagreement without changing an Audiveris export."""
from xml.etree import ElementTree as ET

import pytest

from src.studio.document import inspect, new_score, read_xml, xml_bytes


def two_parts():
    root = read_xml(new_score(template="satb", bars=6, fifths=-3))
    software = root.find("identification/encoding/software")
    if software is None:
        ident = root.find("identification")
        if ident is None:
            ident = ET.SubElement(root, "identification")
        enc = ET.SubElement(ident, "encoding")
        software = ET.SubElement(enc, "software")
    software.text = "Audiveris 5.11.0"
    for part in root.findall("part"):
        for position, fifths in [(2, -2), (4, -3)]:
            bar = part.findall("measure")[position]
            boundary = ET.Element("print", {"new-system": "yes"})
            bar.insert(0, boundary)
            if part is root.find("part"):
                attrs = ET.Element("attributes")
                ET.SubElement(ET.SubElement(attrs, "key"), "fifths").text = str(fifths)
                bar.insert(1, attrs)
    return root


def flags(root):
    return [issue for issue in inspect(root)["issues"] if issue.get("code") == "isolated-system-key"]


def test_transient_key_disagreement_points_to_exact_span_without_mutation():
    root = two_parts()
    original = xml_bytes(root)
    issue, = flags(root)
    assert (issue["part"], issue["measure"], issue["endMeasure"]) == (0, 2, 3)
    assert "2 flats" in issue["message"] and "3 flats" in issue["message"]
    assert xml_bytes(root) == original


@pytest.mark.parametrize("case", ["shared", "transposed", "staff_key", "different_bars", "permanent", "composition"])
def test_ambiguous_or_deliberate_keys_are_left_for_general_review(case):
    root = two_parts()
    parts = root.findall("part")
    bars = parts[0].findall("measure")
    if case == "shared":
        for part in parts[1:]:
            for i in (2, 4):
                part.findall("measure")[i].insert(1, ET.fromstring(ET.tostring(bars[i].find("attributes"))))
    elif case == "transposed":
        ET.SubElement(ET.SubElement(parts[1].find("measure/attributes"), "transpose"), "chromatic").text = "-2"
    elif case == "staff_key":
        bars[2].find("attributes/key").set("number", "1")
    elif case == "different_bars":
        parts[-1].remove(parts[-1].find("measure"))
    elif case == "permanent":
        bars[4].remove(bars[4].find("attributes"))
    else:
        root.find("identification/encoding/software").text = "Author's notation editor"
    assert flags(root) == []
