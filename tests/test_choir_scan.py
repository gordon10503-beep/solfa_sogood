import zipfile

from src.studio.document import engrave, new_score, read_xml, remove_tuplet, replace_bar, xml_bytes, child
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


def test_regular_notes_restore_voice_backup():
    root = read_xml(replace_bar(new_score(template="melody", bars=1, beats=3, beat_type=8), 0, 0, "C4/e D4/e E4/e"))
    m = root.find("part/measure")
    m.find("attributes/divisions").text = "6"
    notes = m.findall("note")[:3]
    for n in notes:
        n.find("duration").text = "2"
        tm = child(n, "time-modification")
        child(tm, "actual-notes", 3)
        child(tm, "normal-notes", 2)
    for n, kind in [(notes[0], "start"), (notes[-1], "stop")]:
        child(child(n, "notations"), "tuplet", type=kind)
    total = sum(int(n.findtext("duration")) for n in m.findall("note"))
    child(child(m, "backup"), "duration", total)
    corrected = read_xml(remove_tuplet(xml_bytes(root), "ss-p0-m0-n0"))
    assert corrected.find(".//time-modification") is None
    assert int(corrected.findtext(".//backup/duration")) == total + 3
