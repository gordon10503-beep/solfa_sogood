"""Replay saved full-score exports against independently transcribed private bars."""
import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from statistics import median
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from benchmarks.choir import CASES
from src.studio.scan_compare import describe, structural_checks


def note_key(onset, pitch, duration):
    match = re.fullmatch(r"([A-G])([#b]*)(-?\d+)", pitch)
    if not match or Fraction(onset) < 0 or Fraction(duration) <= 0:
        raise ValueError(f"Invalid reference event {onset}, {pitch}, {duration}")
    step, signs, octave = match.groups()
    return Fraction(onset), step, Fraction(signs.count("#") - signs.count("b")), int(octave), Fraction(duration)


def load_reference(path, digest):
    ref = json.loads(path.read_text(encoding="utf-8-sig"))
    if ref["sourceSha256"] != digest or ref["case"] != CASES[digest][0]:
        raise ValueError(f"Reference edition mismatch in {path}")
    bars = {}
    for line in ref["passages"]:
        key = line["part"], line["bar"]
        if key in bars or not 0 <= key[0] < len(ref["expectedParts"]) or key[1] < 1:
            raise ValueError(f"Invalid or duplicate reference bar {key}")
        bars[key] = Counter(note_key(*event) for event in line["events"])
    if not bars:
        raise ValueError(f"Empty reference {path}")
    return ref, bars


def assess(data, ref, bars):
    parts, events = describe(data)
    row = {"parts": parts, "structure": structural_checks(data), "noteComparison": None}
    # The answer keys index printed staves in order. A split or missing part
    # invalidates this mapping; zeros here would make an invented accuracy rate.
    if len(parts) != len(ref["expectedParts"]):
        row["mapping"] = "part count mismatch"
        return row, {}
    expected_staves = [2 if name.lower() == "piano" else 1 for name in ref["expectedParts"]]
    if [p["staves"] for p in parts] != expected_staves:
        row["mapping"] = "staff count mismatch"
        return row, {}
    row["mapping"] = "printed part order and bar position"
    actual = defaultdict(Counter)
    for (part, measure, onset, _staff, step, alter, octave, duration), n in events.items():
        key = part, measure + 1
        if key in bars:
            actual[key][onset, step, alter, int(octave), duration] += n
    hits = missing = extra = exact = absent = 0
    differences = {}
    for (p, bar), truth in sorted(bars.items()):
        found = actual[p, bar]
        present = bar <= parts[p]["bars"]
        absent += not present
        exact += present and truth == found
        hits += (truth & found).total()
        missing += (truth - found).total()
        extra += (found - truth).total()
        if truth != found or not present:
            differences[p, bar] = (truth - found, found - truth, not present)
    row["noteComparison"] = {"referencePartBars": len(bars), "exactPartBars": exact,
                             "absentPartBars": absent, "matched": hits, "missing": missing, "extra": extra}
    return row, differences


def event_text(e):
    onset, step, alter, octave, length = e
    accidental = ("#" * int(alter) if alter >= 0 else "b" * -int(alter)) if alter.denominator == 1 else f"({alter})"
    return f"{onset} {step}{accidental}{octave} {length}"


def narrow_system_edges(sheet, page):
    """Locate short end stacks for visual review, including legitimate pickups."""
    findings = []
    for system in sheet.iter("system"):
        stacks = system.findall("stack")
        if len(stacks) < 3:
            continue
        try:
            widths = [int(s.attrib["right"]) - int(s.attrib["left"]) for s in stacks]
        except (KeyError, ValueError):
            continue
        if min(widths) <= 0:
            continue
        for index, edge, neighbors in [(0, "first", widths[1:]), (-1, "last", widths[:-1])]:
            ratio = widths[index] / median(neighbors)
            if ratio < 0.25:
                stack = stacks[index]
                findings.append({"page": page, "systemId": system.get("id"), "edge": edge,
                                 "stackId": stack.get("id"), "relativeWidth": round(ratio, 3),
                                 "engineSpecial": stack.get("special"), "duration": stack.get("duration"),
                                 "expected": stack.get("expected"), "excess": stack.get("excess")})
    return findings


def replay(scans, references, trials=None, inspect_edges=False):
    report = {"runs": [], "repeatedDifferences": [], "unmatchedJobs": []}
    recurrence = defaultdict(list)
    for job in sorted(p for p in scans.iterdir() if p.is_dir()):
        original = job / "scan.pdf"
        digest = hashlib.sha256(original.read_bytes()).hexdigest() if original.exists() else ""
        if digest not in CASES:
            report["unmatchedJobs"].append(job.name)
            continue
        case = CASES[digest][0]
        ref, bars = load_reference(references / (case + ".json"), digest)
        run = {"job": job.name, "case": case, "sourceSha256": digest}
        report["runs"].append(run)
        directory = job / "standard" if (job / "standard").is_dir() else job
        exports = sorted(directory.rglob("*.mxl")) or sorted(directory.rglob("*.musicxml"))
        if len(exports) != 1:
            run["status"] = "missing export" if not exports else "ambiguous export"
            continue
        # A scan may have used the same original PDF with the -sheets option.
        books = [p for p in directory.rglob("*.omr") if not p.name.endswith(".original.omr")]
        import pymupdf
        with pymupdf.open(original) as pdf:
            pages = set(range(1, len(pdf)+1))
        if len(books) != 1:
            run["status"] = "unverified page coverage"
            continue
        with ZipFile(books[0]) as book:
            sheets = {int(m[1]) for n in book.namelist()
                      if (m := re.fullmatch(r"sheet#(\d+)/sheet#\1\.xml", n))}
            if inspect_edges and sheets == pages:
                run["narrowSystemEdges"] = []
                for page in sorted(sheets):
                    with book.open(f"sheet#{page}/sheet#{page}.xml") as xml:
                        run["narrowSystemEdges"].extend(narrow_system_edges(ET.parse(xml).getroot(), page))
        if sheets != pages:
            run["status"] = "partial book"
            continue
        stages = {"saved": exports[0]}
        if trials:
            for stage in ("baseline", "candidate"):
                path = trials / job.name / stage / "score.mxl"
                if path.exists():
                    stages[stage] = path
        for stage, path in stages.items():
            data = path.read_bytes()
            try:
                result, differences = assess(data, ref, bars)
            except (ValueError, KeyError, IndexError, ArithmeticError, SyntaxError) as error:
                run[stage] = {"error": str(error)}
                continue
            run[stage] = result
            result["exportSha256"] = hashlib.sha256(data).hexdigest()
            if stage == "saved":
                for (part, bar), (lost, added, absent) in differences.items():
                    if absent:
                        recurrence[case, part, bar, "absent bar", ""].append(job.name)
                    for kind, diff in [("missing", lost), ("extra", added)]:
                        for event in diff:
                            recurrence[case, part, bar, kind, event_text(event)].append(job.name)
        run["status"] = "export read" if "error" not in run["saved"] else "unreadable export"
    for (case, part, bar, kind, event), jobs in sorted(recurrence.items()):
        if len(jobs) > 1:
            report["repeatedDifferences"].append({"case": case, "partIndex": part, "bar": bar, "kind": kind,
                                                  "onsetPitchDuration": event, "jobCount": len(jobs), "jobs": jobs})
    return report


def export_pairs(scans, destination):
    """Export the same saved recognition graph twice; the only variable is part assembly."""
    from src.studio.scan_options import repair_empty_run_tables, repair_satb_book
    from src.studio.server import audiveris_path
    engine = audiveris_path()
    if not engine:
        raise ValueError("Install Audiveris before exporting comparison pairs.")
    destination.mkdir(parents=True, exist_ok=False)
    for job in sorted(scans.iterdir()):
        source = job / "scan.pdf"
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() not in CASES:
            continue
        directory = job / "standard" if (job / "standard").is_dir() else job
        books = [p for p in directory.rglob("*.omr") if not p.name.endswith(".original.omr")]
        if len(books) != 1:
            continue
        for stage in ("candidate", "baseline"):
            work = (destination / job.name / stage).resolve()
            work.mkdir(parents=True)
            book = work / "score.omr"
            shutil.copyfile(books[0], book)
            if stage == "candidate" and not repair_satb_book(book, "auto"):
                break
            repair_empty_run_tables(book)
            with (work / "export.log").open("w", encoding="utf-8") as log:
                subprocess.run([str(engine), "-batch", "-export", "-output", str(work), "--", str(book)],
                               stdout=log, stderr=subprocess.STDOUT, timeout=300, check=True)
            if not (work / "score.mxl").is_file():
                raise ValueError(f"Missing {stage} export for {job.name}. See {work / 'export.log'}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scans", type=Path, default=Path("data/scans"))
    parser.add_argument("--references", type=Path, default=Path("data/benchmark-references"))
    parser.add_argument("--inspect-edges", action="store_true", help="Report unusually narrow system-edge measures for PDF review")
    experiment = parser.add_mutually_exclusive_group()
    experiment.add_argument("--trials", type=Path, help="Existing paired exports in JOB/{baseline,candidate}/score.mxl")
    experiment.add_argument("--export-pairs", type=Path, help="Re-export eligible books to a new directory")
    parser.add_argument("--report", type=Path, default=Path("data/benchmark-references/replay.json"))
    args = parser.parse_args()
    if args.export_pairs:
        export_pairs(args.scans, args.export_pairs)
    report = replay(args.scans, args.references, args.trials or args.export_pairs, args.inspect_edges)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for run in report["runs"]:
        print(run["case"], run["job"][:8], run["status"], (run.get("saved") or {}).get("noteComparison"))
    print("Detailed results:", args.report)


if __name__ == "__main__":
    main()
