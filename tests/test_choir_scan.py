import zipfile
import pytest

from src.studio.document import engrave, new_score, read_xml, remove_tuplet, repair_octave, replace_bar, xml_bytes, child
from src.studio.scan_options import repair_empty_run_tables


def test_book_repairs_only_zero_width_inkless_table(tmp_path):
    path = tmp_path / "scan.omr"
    good = b'<run-table orientation="VERTICAL" width="2" height="8"><runs>1</runs></run-table>'
    broken = b'<run-table orientation="VERTICAL" width="0" height="14"/>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sheet#3/sheet#3.xml", b"<sheet>" + good + broken + b"</sheet>")
        archive.writestr("book.xml", b"<book/>")
    repair_empty_run_tables(path)
    with zipfile.ZipFile(path) as archive:
        data = archive.read("sheet#3/sheet#3.xml")
        assert good in data and broken not in data and b"<runs/>" in data
        assert archive.read("book.xml") == b"<book/>"


def test_reader_condenses_resting_voices_and_keeps_sound():
    score = replace_bar(new_score(bars=2), 0, 0, "C4/w")
    normal, compact = engrave(score), engrave(score, compact=True)
    assert normal["events"] == compact["events"]
    assert compact["pages"][0].count('class="staff"') < normal["pages"][0].count('class="staff"')


@pytest.mark.parametrize("explicit", [True, False])
def test_regular_notes_restore_voice_backup(explicit):
    root = read_xml(replace_bar(new_score(template="melody", bars=1, beats=3, beat_type=8), 0, 0, "C4/e D4/e E4/e"))
    m = root.find("part/measure")
    m.find("attributes/divisions").text = "6"
    notes = m.findall("note")[:3]
    for n in notes:
        n.find("duration").text = "2"
        tm = child(n, "time-modification")
        child(tm, "actual-notes", 3)
        child(tm, "normal-notes", 2)
    if explicit:
        for n, kind in [(notes[0], "start"), (notes[-1], "stop")]:
            child(child(n, "notations"), "tuplet", type=kind)
    total = sum(int(n.findtext("duration")) for n in m.findall("note"))
    child(child(m, "backup"), "duration", total)
    corrected = read_xml(remove_tuplet(xml_bytes(root), "ss-p0-m0-n0"))
    assert corrected.find(".//time-modification") is None
    assert int(corrected.findtext(".//backup/duration")) == total + 3


def test_octave_candidate_requires_peer_and_unclosed_mark():
    score = new_score(bars=2)
    for part, bar, pitch in [(0, 0, "A6/w"), (0, 1, "A4/w"), (1, 0, "A4/w")]:
        score = replace_bar(score, part, bar, pitch)
    root = read_xml(score)
    first, peer = [p.find("measure") for p in root.findall("part")[:2]]
    for measure in (first, peer):
        note = measure.find("note")
        note.set("default-x", "200")
        child(note, "stem", "up", **{"default-y": "-20"})
        child(child(note, "lyric"), "text", "ah")
    direction = child(first, "direction")
    child(child(direction, "direction-type"), "octave-shift", type="down", size="15")
    first.remove(direction)
    first.insert(list(first).index(first.find("note")), direction)
    corrected = read_xml(repair_octave(xml_bytes(root), 0, 0))
    assert corrected.findtext("part/measure/note/pitch/octave") == "4"
    assert corrected.find(".//octave-shift") is None
    peer.find("note").set("default-x", "195")
    with pytest.raises(ValueError, match="No corroborated"):
        repair_octave(xml_bytes(root), 0, 0)
    peer.find("note").set("default-x", "200")
    stop = child(root.findall("part")[0].findall("measure")[1], "direction")
    child(child(stop, "direction-type"), "octave-shift", type="stop")
    with pytest.raises(ValueError, match="No corroborated"):
        repair_octave(xml_bytes(root), 0, 0)
