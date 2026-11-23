"""Optional Java exporter regression on the private Grow for Me recognition book."""
import os
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from src.studio.document import read_xml
from src.studio.server import audiveris_path


@pytest.mark.parametrize("condition", ["original", "manual", "without-ties"])
def test_grow_lyric_line_export(tmp_path, condition):
    source = os.environ.get("SOLFA_GROW_OMR")
    if not source:
        pytest.skip("Set SOLFA_GROW_OMR to the private four-page benchmark book.")
    engine = audiveris_path()
    assert engine, "Install the Studio-patched Audiveris engine to run this integration test."
    book = tmp_path / "score.omr"
    with ZipFile(Path(source)) as original, ZipFile(book, "w") as copy:
        for item in original.infolist():
            data = original.read(item)
            if item.filename == "sheet#4/sheet#4.xml" and condition != "original":
                page = ET.fromstring(data)
                last_system = list(page.iter("system"))[-1]
                ending, = last_system.iter("ending")
                if condition == "manual":
                    ending.set("manual", "true")
                else:
                    for slur in last_system.iter("slur"):
                        slur.attrib.pop("tie", None)
                data = ET.tostring(page, encoding="utf-8", xml_declaration=True)
            copy.writestr(item, data)

    subprocess.run([str(engine), "-batch", "-export", "-output", str(tmp_path), "--", str(book)],
                   check=True, timeout=180)
    root = read_xml(next(tmp_path.rglob("*.mxl")).read_bytes())
    vocal, piano = root.findall("part")
    assert len(piano.findall("measure")) == len(vocal.findall("measure")) == 61
    assert vocal.findall("measure")[16].find("barline/repeat[@direction='backward']") is not None
    assert vocal.findall("measure")[17].find("barline/ending[@type='start'][@number='2']") is not None
    marks = [(i, mark.get("type")) for i, bar in enumerate(piano.findall("measure"), 1)
             if 57 <= i <= 60 for mark in bar.findall("barline/ending")]
    assert marks == ([] if condition == "original" else [(57, "start"), (60, "discontinue")])
