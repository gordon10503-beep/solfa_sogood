import xml.etree.ElementTree as ET

import pytest

from src.studio.document import inspect, new_score, read_xml
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
