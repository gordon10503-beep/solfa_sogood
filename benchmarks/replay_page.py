"""Compare three first-page inputs against the private reference, leaving all library files intact."""
import argparse
from pathlib import Path
from tempfile import mkdtemp
from time import monotonic
import hashlib
import json

import pymupdf

from benchmarks.replay import CASES, assess, load_reference
from src.studio.scan_preprocess import prepare_for_omr
from src.studio.server import audiveris_path, recognize_book


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--references", type=Path, default=Path("data/benchmark-references"))
    args = parser.parse_args()
    digest = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    if digest not in CASES:
        parser.error("This PDF edition has no reference.")
    case = CASES[digest][0]
    ref, bars = load_reference(args.references / (case + ".json"), digest)
    keys = {(p["part"], p["bar"]) for p in ref["passages"] if p["page"] == 1}
    if not keys:
        parser.error("This edition has no verified opening passages.")
    work = Path(mkdtemp(prefix="solfa-page-trial-")).resolve()
    source = work / "page.pdf"
    with pymupdf.open(args.pdf) as original, pymupdf.open() as one:
        one.insert_pdf(original, from_page=0, to_page=0)
        one.save(source)
    prepared = prepare_for_omr(source)
    engine = audiveris_path()
    if not engine:
        parser.error("Audiveris is required.")
    print("Trial directory:", work, flush=True)
    for name, page, flags in [
        ("prepared", prepared, []), ("original", source, []),
        ("prepared-400dpi", prepared, ["-constant", "org.audiveris.omr.image.ImageLoading.pdfResolution=400"]),
    ]:
        folder = work / name
        folder.mkdir()
        start = monotonic()
        with (folder / "recognition.log").open("w", encoding="utf-8") as log:
            data, _ = recognize_book(engine, page, folder, flags, [], "auto", log, lambda *_: None)
        metrics, _ = assess(data, ref, {k: bars[k] for k in keys})
        metrics["seconds"] = round(monotonic()-start, 2)
        (folder / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(name, metrics["noteComparison"], flush=True)


if __name__ == "__main__":
    main()
