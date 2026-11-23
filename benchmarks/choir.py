"""Run a fresh Studio scan on a known private rehearsal score."""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
from time import monotonic
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from src.studio.document import inspect, read_xml
from src.studio.playback import measure_order
from src.studio.recognition_profile import experiment_flags
from src.studio.scan_compare import compare, describe, structural_checks
from src.studio.server import Library, audiveris_path, recognize_book, scan


CASES = {
    "895f916c4625a3f34f0a5e5a59a7562268ae8492e098fd238492bac3c3d55536": ("advanced", "satb-piano"),
    "2f2f0f294bffba8eb2ecba44b0e1c5138ae33e96998858f78ada95604ea786a6": ("middle", "auto"),
    "6044fe099720b5890ede468040edaee281d63cdfdf8281f03ec3511019f56b78": ("grow", "auto"),
}

# Manually read from the printed first voice. Each row is a complete bar
# in the checked excerpt. Times are in eighth notes, including pickup bars.
VOCAL_BARS = {
    "middle": {3: [(2, "C#4", 2), (4, "F#4", 2), (6, "A#4", 2)]},
    "grow": {
        1: [(0, "Bb3", 1), (1, "Bb3", 1), (2, "Eb4", 1), (3, "F4", 1)],
        2: [(0, "G4", 2), (2, "Eb4", 1), (3, "Eb4", 3)],
        3: [(2, "Bb3", 1), (3, "Bb3", 1), (4, "Eb4", 1), (5, "G4", 1)],
        4: [(0, "Bb4", 3)],
    },
}


def vocal_excerpt(case, data):
    bars = VOCAL_BARS[case]
    expected = Counter()
    for bar, notes in bars.items():
        for onset, pitch, length in notes:
            alteration = {"": 0, "#": 1, "b": -1}[pitch[1:-1]]
            expected[0, bar-1, Fraction(onset, 2), "1", pitch[0], alteration, pitch[-1], Fraction(length, 2)] += 1
    _, events = describe(data)
    observed = Counter({k: n for k, n in events.items() if k[0] == 0 and k[1]+1 in bars})
    return {"bars": list(bars), "expected": expected.total(), "matched": (expected & observed).total(),
            "missing": (expected-observed).total(), "extra": (observed-expected).total()}


def lyric_tuplet_checks(pdf, book):
    """Two visually checked negative examples in the pinned advanced edition."""
    import pymupdf
    results = []
    with pymupdf.open(stream=pdf, filetype="pdf") as doc, ZipFile(book) as archive:
        for number, character, anchor in [(5, "何", (174, 108)), (8, "過", (521, 114))]:
            page = doc[number-1]
            word = next(pymupdf.Rect(w[:4]) for w in page.get_text("words")
                        if w[4] == character and pymupdf.Point(anchor) in pymupdf.Rect(w[:4]))
            name = f"sheet#{number}/sheet#{number}.xml"
            matches = None
            if name in archive.namelist():
                sheet = ET.fromstring(archive.read(name))
                picture = sheet.find("picture")
                sx = page.rect.width / int(picture.get("width"))
                sy = page.rect.height / int(picture.get("height"))
                matches = []
                for tuplet in sheet.iter("tuplet"):
                    bounds = tuplet.find("bounds")
                    if bounds is None:
                        continue
                    x, y, w, h = (int(bounds.get(k)) for k in ("x", "y", "w", "h"))
                    if pymupdf.Point((x+w/2)*sx, (y+h/2)*sy) in word:
                        matches.append(tuplet.get("shape"))
            results.append({"page": number, "lyric": character, "expectedTuplets": [],
                            "observedTuplets": matches})
    return results


def opening_trial(pdf, case, engine, folder, profile):
    import pymupdf
    source = folder / "page.pdf"
    with pymupdf.open(stream=pdf, filetype="pdf") as original, pymupdf.open() as first:
        first.insert_pdf(original, from_page=0, to_page=0)
        first.save(source)
    records = {}
    baseline = None
    for name in ("Standard", profile):
        dest = folder / name
        dest.mkdir()
        flags = experiment_flags("Leland" if name == "Leland" else None, "Poor" if name == "Poor" else "Standard")
        start = monotonic()
        with (dest / "log").open("w", encoding="utf8") as log:
            score, _ = recognize_book(engine, source, dest, flags, [], "auto", log, lambda *_: None)
        elapsed = monotonic()-start
        (dest / "result.mxl").write_bytes(score)
        result = describe(score)
        if baseline is None:
            baseline = result
        records[name] = {"seconds": round(elapsed, 2), "settings": flags, "structure": structural_checks(score),
                         "againstStandard": compare(baseline, result)}
        if case in VOCAL_BARS:
            records[name]["checkedVocalExcerpt"] = vocal_excerpt(case, score)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--opening-profile", choices=["Poor", "Leland"],
                        help="Compare one alternative against Standard on the complete first page.")
    args = parser.parse_args()
    data = args.pdf.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest not in CASES:
        parser.error("The PDF does not match a benchmark edition.")
    case, layout = CASES[digest]
    engine = audiveris_path()
    if not engine:
        parser.error("Audiveris is required to benchmark scanning.")
    folder = Path(tempfile.mkdtemp(prefix="solfa-benchmark-"))
    if args.opening_profile:
        print("Benchmark artifacts:", folder, flush=True)
        report = opening_trial(data, case, engine, folder, args.opening_profile)
        (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf8")
        print(json.dumps(report, indent=2))
        return 0
    workspace = SimpleNamespace(library=Library(folder / "bench.db"), jobs={})
    start = monotonic()
    scan(workspace, case, engine, data, ".pdf", options={"layout": layout})
    job = workspace.jobs[case]
    report = {"case": case, "sha256": digest, "status": job["status"], "seconds": round(monotonic()-start, 1),
              "artifacts": str(folder)}
    if job["status"] == "done":
        score = workspace.library.get(job["id"])["xml"]
        root = read_xml(score)
        if case in VOCAL_BARS:
            report["checkedVocalExcerpt"] = vocal_excerpt(case, score)
        info = inspect(root)
        report["parts"] = [{"name": p["name"], "bars": len(p["measures"])} for p in info["parts"]]
        report["recognizedTupletGroups"] = dict(Counter(n["tupletStart"] for n in info["notes"].values() if "tupletStart" in n))
        report["openingQuarterBpm"] = [t["bpm"] for t in info["parts"][0]["measures"][0]["tempos"] if t["offset"] == 0]
        if case == "advanced":
            scan_dir = folder / "scans" / case
            final_pass = scan_dir / "standard" if (scan_dir / "standard").is_dir() else scan_dir
            book = next(final_pass.rglob("*.omr"), None)
            report["checkedTupletsOverLyrics"] = lyric_tuplet_checks(data, book) if book else None
            report["partsWith55PrintedBars"] = sum(p["bars"] == 55 for p in report["parts"])
            report["openingTempoMatchesPrint"] = report["openingQuarterBpm"] == [108]
        if case == "grow":
            order = [i+1 for i in measure_order(root, max(p["bars"] for p in report["parts"]))]
            jumps = [(a, b) for a, b in zip(order, order[1:]) if b != a+1]
            report["repeatJumps"] = jumps
            report["matchesFirstAndSecondEndingOnPageTwo"] = jumps[:2] == [(17, 2), (13, 18)]
            # The last printed system has a vocal lyric extender above piano.
            # Missing/misgrouped parts are not evidence that a false ending was fixed.
            piano = next((p for p, info in zip(root.findall("part"), report["parts"])
                          if info["name"].strip().lower() == "piano" and info["bars"] == 61), None)
            report["endingMarksOverFinalLyricExtender"] = None if piano is None else [
                {"bar": i, "type": mark.get("type"), "number": mark.get("number")}
                for i, bar in enumerate(piano.findall("measure"), 1) if 57 <= i <= 60
                for mark in bar.findall("barline/ending")]
    else:
        report["error"] = job["error"]
    print(json.dumps(report, indent=2))
    return int(job["status"] != "done")


if __name__ == "__main__":
    raise SystemExit(main())
