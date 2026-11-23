import xml.etree.ElementTree as ET

import pytest

from src.studio.document import extend_first_ending, inspect, new_score, read_xml, xml_bytes
from src.studio.playback import build_playback


def test_compound_meter_repeat_restores_inherited_dotted_tempo():
    root = read_xml(new_score(template="melody", bars=3, beats=12, beat_type=8))
    first, start, end = root.findall("part/measure")
    opening = first.find("direction")
    opening.remove(opening.find("sound"))
    metronome = opening.find("direction-type/metronome")
    metronome.find("per-minute").text = "72"
    metronome.insert(1, ET.Element("beat-unit-dot"))
    start.insert(0, ET.fromstring('<barline location="left"><repeat direction="forward"/></barline>'))
    end.insert(0, ET.fromstring('<direction><sound tempo="60"/></direction>'))
    end.append(ET.fromstring('<barline location="right"><repeat direction="backward"/></barline>'))

    result = build_playback(root, inspect(root))
    assert result["baseTempo"] == 108
    assert [m["measure"] for m in result["measureTimes"]] == [0, 1, 2, 1, 2]
    assert result["duration"] == pytest.approx(3 * (4 * 60 / 72) + 2 * 6)


@pytest.mark.parametrize("direction,expected", [
    ('<direction><offset>16</offset><sound tempo="60"/></direction>', 0),
    ('<direction><offset sound="yes">16</offset><sound tempo="60"/></direction>', 1),
    ('<direction><offset sound="yes">16</offset><sound tempo="60"><offset>32</offset></sound></direction>', 2),
    ('<sound tempo="60"><offset>32</offset></sound>', 2),
])
def test_mid_measure_tempo_uses_playback_offset(direction, expected):
    root = read_xml(new_score(template="melody", bars=1))
    bar = root.find("part/measure")
    bar.remove(bar.find("direction"))
    bar.insert(1, ET.fromstring(direction))
    result = build_playback(root, inspect(root))
    assert result["duration"] == pytest.approx(expected * .5 + (4 - expected))


@pytest.mark.parametrize("stop, attacks", [(True, 1), (False, 2)])
def test_vocal_tie_over_overfilled_accompaniment(stop, attacks):
    root = read_xml(new_score(template="satb", bars=2))
    a, b = root.findall("part")[0].findall("measure/note")
    for note in (a, b):
        note.remove(note.find("rest"))
        note.insert(0, ET.fromstring("<pitch><step>C</step><octave>4</octave></pitch>"))
    ET.SubElement(a, "tie", type="start")
    if stop:
        ET.SubElement(b, "tie", type="stop")
    accompaniment = root.findall("part")[-1].find("measure/note/duration")
    accompaniment.text = str(int(accompaniment.text)*2)
    result = build_playback(root, inspect(root))
    events = [e for e in result["events"] if e["part"] == 0]
    assert len(events) == attacks
    if stop:
        assert events[0]["duration"] == pytest.approx(result["duration"])


def test_lower_staff_repeat_and_pass_reset_after_second_ending():
    root = read_xml(new_score(template="satb", bars=6))
    bars = root.findall("part")[-1].findall("measure")
    def line(index, location, name, **attrs):
        ET.SubElement(ET.SubElement(bars[index], "barline", location=location), name, attrs)
    line(0, "right", "repeat", direction="forward")
    line(2, "left", "ending", type="start", number="1")
    line(2, "right", "ending", type="stop", number="1")
    line(2, "right", "repeat", direction="backward")
    line(3, "left", "ending", type="start", number="2")
    line(3, "right", "ending", type="stop", number="2")
    line(5, "left", "ending", type="start", number="1")
    order = [b["measure"] for b in build_playback(root, inspect(root))["measureTimes"]]
    assert order == [0, 1, 2, 1, 3, 4, 5]
    assert inspect(root)["shortFirstEndings"] == [2]
    data = xml_bytes(root)
    changed = read_xml(extend_first_ending(data, end_bar=2, start_bar=1))
    assert [b["measure"] for b in build_playback(changed, inspect(changed))["measureTimes"]] == [0, 1, 2, 3, 4, 5]
    with pytest.raises(ValueError, match="cross an existing repeat"):
        extend_first_ending(data, end_bar=2, start_bar=0)
