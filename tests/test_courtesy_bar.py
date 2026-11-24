from xml.etree import ElementTree as ET

import pytest

from src.studio.courtesy import candidates, remove_confirmed
from src.studio.document import inspect


def scanned():
    root = ET.fromstring("<score-partwise><identification><encoding><software>Audiveris 5.11.0</software>"
                         "</encoding></identification></score-partwise>")
    for i in range(3):
        part = ET.SubElement(root, "part", id=f"P{i}")
        bars = """<measure number="1" width="410"><attributes><divisions>1</divisions>
          <key><fifths>1</fifths></key><time><beats>3</beats><beat-type>4</beat-type></time></attributes>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>3</duration><tie type="start"/></note>
          <barline location="right"><bar-style>light-light</bar-style></barline></measure>
          <measure number="2" width="75"><attributes><key><fifths>4</fifths></key></attributes></measure>
          <measure number="3" width="300"><print new-system="yes"/><attributes><divisions>2</divisions>
          <time><beats>6</beats><beat-type>8</beat-type></time></attributes>
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>6</duration><tie type="stop"/></note></measure>"""
        part.extend(ET.fromstring("<bars>" + bars + "</bars>"))
    root.findall("part")[-1][1].append(ET.fromstring(
        "<note><pitch><step>F</step><octave>4</octave></pitch><duration>4</duration></note>"))
    return root


def test_confirmed_courtesy_repair_carries_key_and_preserves_following_material():
    root = scanned()
    assert [(i, parts) for i, parts in candidates(root)] == [(1, [2])]
    assert inspect(root)["issues"][0]["code"] == "courtesy-bar"
    remove_confirmed(root, 1)
    for part in root.findall("part"):
        assert [m.get("number") for m in part] == ["1", "2"]
        assert [el.tag for el in part[1].find("attributes")] == ["divisions", "key", "time"]
        assert part[1].findtext("attributes/key/fifths") == "4"
        assert part[1].findtext("attributes/time/beat-type") == "8"
        assert part[1].find("print").get("new-system") == "yes"
        assert [el.get("type") for el in part.iter("tie")] == ["start", "stop"]
    with pytest.raises(ValueError):
        remove_confirmed(root, 1)


@pytest.mark.parametrize("element", ["tie", "lyric", "notations", "beam", "time-modification"])
def test_linked_or_annotated_candidate_is_not_removable(element):
    root = scanned()
    root.findall("part")[-1][1].find("note").append(ET.Element(element))
    before = ET.tostring(root)
    with pytest.raises(ValueError):
        remove_confirmed(root, 1)
    assert ET.tostring(root) == before


@pytest.mark.parametrize("mutation", ["repeat", "mixed-bar-order", "next-key", "wide", "no-system-break", "authored", "more-voices"])
def test_declines_ambiguous_or_musical_boundaries(mutation):
    root = scanned()
    a, b, c = root.findall("part")
    if mutation == "repeat":
        b[0].find("barline").append(ET.Element("repeat", direction="backward"))
    elif mutation == "mixed-bar-order":
        c[2].set("number", "4")
    elif mutation == "next-key":
        a[2].find("attributes").append(ET.fromstring("<key><fifths>-2</fifths></key>"))
    elif mutation == "wide":
        a[1].set("width", "250")
    elif mutation == "no-system-break":
        a[2].remove(a[2].find("print"))
    elif mutation == "authored":
        root.find(".//software").text = "Composer"
    else:
        b[1].append(c[1].find("note"))
    assert not list(candidates(root))
