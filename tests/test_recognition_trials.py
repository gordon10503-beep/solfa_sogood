from pathlib import Path
from types import SimpleNamespace
import hashlib
import xml.etree.ElementTree as ET

import pymupdf
import pytest

from src.studio import server
from src.studio.document import read_xml, xml_bytes
from src.studio.recognition_profile import experiment_flags, page_evidence
from src.studio.scan_compare import compare, describe, structural_checks

FIXTURES = Path(__file__).resolve().parents[1] / "benchmarks/fixtures"


def test_exact_events_distinguish_part_order_and_timing():
    data = (FIXTURES/"duet.musicxml").read_bytes()
    root = read_xml(data)
    note = root.find("part/measure/note/duration")
    note.text = str(int(note.text) - 1)
    report = compare(describe(data), describe(xml_bytes(root)))
    assert report["partNamesAndStavesMatch"] and report["barCountsMatch"]
    assert report["baselineOnly"] > 0 and report["candidateOnly"] > 0
    assert report["baselineExamples"][0]["part"] == 1
    assert structural_checks(xml_bytes(root))["inspectionFindings"]
    root.append(root.findall("part")[0])
    assert not structural_checks(xml_bytes(root))["validPartIds"]


def test_page_comparison_abstains_on_incomplete_page_maps():
    root = read_xml((FIXTURES/"duet.musicxml").read_bytes())
    for part in root.findall("part"):
        part.findall("measure")[2].insert(0, ET.Element("print", {"new-page":"yes"}))
    parts, events = describe(xml_bytes(root), 2, 2)
    assert [p["bars"] for p in parts] == [2, 2] and min(k[1] for k in events) == 0
    measure = root.findall("part")[1].findall("measure")[2]
    measure.remove(measure.find("print"))
    assert describe(xml_bytes(root), 2, 2) is None


def test_profiles_require_positive_evidence():
    with pymupdf.open(FIXTURES/"satb.pdf") as doc:
        assert page_evidence(doc[0]) == (None, None)
        doc.set_metadata({"creator":"MuseScore"})
        assert page_evidence(doc[0]) == (None, "Synthetic")
    with pymupdf.open() as doc:
        assert page_evidence(doc.new_page()) == (None,None)
    assert experiment_flags() == []
    assert experiment_flags("Leland","Synthetic")[1].endswith("defaultMusicFamily=Leland")
    with pytest.raises(ValueError):
        experiment_flags("unknown")


def test_optional_page_trial_creates_separate_candidate(tmp_path, monkeypatch):
    lib = server.Library(tmp_path/"trial.db")
    data = (FIXTURES/"duet.musicxml").read_bytes()
    pdf = (FIXTURES/"duet.pdf").read_bytes()
    sid = lib.add(data, {"origin":"Scan"}, pdf, "application/pdf")
    before = lib.get(sid)
    space = SimpleNamespace(library=lib, jobs={"job":{"name":"Compare"}}, public_host=False)
    attempts = []
    def recognize(command, source, folder, flags, sheets, layout, log, progress):
        with pymupdf.open(source) as doc:
            assert len(doc) == 1
        attempts.append(flags)
        return data, None
    monkeypatch.setattr(server, "recognize_book", recognize)
    server.page_trial(space, "job", "engine", before, 1, [1], "synthetic")
    assert space.jobs["job"]["status"] == "done", space.jobs["job"]
    candidate = lib.get(space.jobs["job"]["id"])
    meta = candidate["meta"]["pageTrial"]
    assert len(attempts) == 1 and meta["comparison"]["matched"] == 23
    assert meta["sourceSHA256"] == hashlib.sha256(pdf).hexdigest()
    assert candidate["id"] != sid and lib.get(sid) == before
