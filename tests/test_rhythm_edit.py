"""Score-reader length gestures retain written pitch and fail safely on linked music."""
from xml.etree import ElementTree as ET

import pytest

from src.studio.document import inspect, new_score, read_xml, replace_bar, xml_bytes
from src.studio.rhythm_edit import resize_note


def test_drag_duration_preserves_pitch_marks_and_lyrics_and_moves_next_onset():
    source = replace_bar(new_score(template="melody", bars=1), 0, 0, "C4/q D4/q E4/h")
    root = read_xml(source)
    first = root.find("part/measure/note")
    ET.SubElement(first.find("pitch"), "alter").text = "1"
    ET.SubElement(ET.SubElement(first, "lyric"), "text").text = "la"
    note_id = next(iter(inspect(root)["notes"]))
    changed = read_xml(resize_note(xml_bytes(root), note_id, "eighth", True))
    new = changed.find("part/measure/note")
    assert ET.tostring(new.find("pitch")) == ET.tostring(first.find("pitch"))
    assert new.findtext("lyric/text") == "la"
    assert new.find("dot") is not None
    assert new.findtext("type") == "eighth"
    assert list(inspect(changed)["notes"].values())[1]["offset"] == .75


def test_drag_shortens_full_bar_rest_and_rejects_overfill_or_linked_edits():
    source = new_score(template="melody", bars=1)
    nid = next(iter(inspect(read_xml(source))["notes"]))
    new = read_xml(resize_note(source, nid, "half"))
    assert new.find("part/measure/note/rest").get("measure") is None
    assert inspect(new)["parts"][0]["measures"][0]["extent"] == 2
    with pytest.raises(ValueError, match="exceeds the bar"):
        resize_note(source, nid, "whole", True)
    note = new.find("part/measure/note")
    ET.SubElement(note, "time-modification")
    with pytest.raises(ValueError, match="linked"):
        resize_note(xml_bytes(new), nid, "quarter")
