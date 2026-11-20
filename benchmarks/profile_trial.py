"""Full-page Audiveris ablations against independently supplied source MusicXML."""
import argparse
import hashlib
import json
from pathlib import Path
from time import monotonic

from src.studio.recognition_profile import experiment_flags
from src.studio.pdf_resolution import dense_score_dpi
from src.studio.scan_compare import compare, describe, structural_checks
from src.studio.server import audiveris_path, recognize_book


def trial(pdf, reference, out, font, quality):
    out.mkdir(parents=True, exist_ok=False)
    engine = audiveris_path()
    if not engine:
        raise RuntimeError("Install Audiveris 5.11.0 or configure AUDIVERIS_CMD.")
    expected = describe(reference.read_bytes())
    report = {"pdfSHA256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
              "referenceSHA256": hashlib.sha256(reference.read_bytes()).hexdigest(),
              "engine": str(engine), "profiles": {}}
    profiles = [("baseline", None, None, None), ("font", font, None, None),
                ("quality", None, quality, None), ("both", font, quality, None)]
    dpi = dense_score_dpi(pdf.read_bytes(), [], 16_000_000)
    if dpi:
        profiles.extend([("studio-dpi", None, None, dpi), ("studio-dpi-font", font, None, dpi),
                         ("studio-dpi-quality", None, quality, dpi), ("studio-dpi-both", font, quality, dpi)])
    for name, family, image, resolution in profiles:
        dest = out / name
        dest.mkdir()
        settings = experiment_flags(family, image)
        if resolution:
            settings.extend(["-constant", f"org.audiveris.omr.image.ImageLoading.pdfResolution={resolution}"])
        record = report["profiles"][name] = {"settings": settings, "outputSuccess": False}
        start = monotonic()
        try:
            with (dest / "recognition.log").open("w", encoding="utf8") as log:
                # ASCII scratch name also works with the Windows engine launcher.
                source = dest / "scan.pdf"
                source.write_bytes(pdf.read_bytes())
                result, _ = recognize_book(engine, source, dest, settings, [], "auto", log, lambda *_: None)
            (dest / "result.mxl").write_bytes(result)
            record.update(outputSuccess=True, comparison=compare(expected, describe(result)),
                          structure=structural_checks(result))
        except Exception as exc:
            record["error"] = str(exc)
        record["seconds"] = round(monotonic()-start, 2)
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("verified_musicxml", type=Path)
    parser.add_argument("new_output_directory", type=Path)
    parser.add_argument("--font", required=True, choices=["Bravura", "Leland"])
    parser.add_argument("--quality", required=True, choices=["Synthetic", "Poor", "Standard"])
    args = parser.parse_args()
    result = trial(args.pdf.resolve(), args.verified_musicxml, args.new_output_directory.resolve(), args.font, args.quality)
    raise SystemExit(int(any(not p["outputSuccess"] for p in result["profiles"].values())))
