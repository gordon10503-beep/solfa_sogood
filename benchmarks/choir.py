"""Run a fresh Studio scan against either private choir benchmark."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
from time import monotonic
from types import SimpleNamespace

from src.studio.document import inspect, read_xml
from src.studio.server import Library, audiveris_path, scan


CASES = {
    "895f916c4625a3f34f0a5e5a59a7562268ae8492e098fd238492bac3c3d55536": ("advanced", "satb-piano"),
    "2f2f0f294bffba8eb2ecba44b0e1c5138ae33e96998858f78ada95604ea786a6": ("middle", "auto"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    data = args.pdf.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest not in CASES:
        parser.error("The PDF does not match either benchmark edition.")
    case, layout = CASES[digest]
    engine = audiveris_path()
    if not engine:
        parser.error("Audiveris is required to benchmark scanning.")
    folder = Path(tempfile.mkdtemp(prefix="solfa-benchmark-"))
    workspace = SimpleNamespace(library=Library(folder / "bench.db"), jobs={})
    start = monotonic()
    scan(workspace, case, engine, data, ".pdf", options={"layout": layout})
    job = workspace.jobs[case]
    report = {"case": case, "sha256": digest, "status": job["status"], "seconds": round(monotonic()-start, 1),
              "artifacts": str(folder)}
    if job["status"] == "done":
        root = read_xml(workspace.library.get(job["id"])["xml"])
        info = inspect(root)
        report["parts"] = [{"name": p["name"], "bars": len(p["measures"])} for p in info["parts"]]
        report["recognizedTupletGroups"] = dict(Counter(n["tupletStart"] for n in info["notes"].values() if "tupletStart" in n))
        report["openingQuarterBpm"] = [t["bpm"] for t in info["parts"][0]["measures"][0]["tempos"] if t["offset"] == 0]
        if case == "advanced":
            report["partsWith55PrintedBars"] = sum(p["bars"] == 55 for p in report["parts"])
            report["openingTempoMatchesPrint"] = report["openingQuarterBpm"] == [108]
    else:
        report["error"] = job["error"]
    print(json.dumps(report, indent=2))
    return int(job["status"] != "done")


if __name__ == "__main__":
    raise SystemExit(main())
