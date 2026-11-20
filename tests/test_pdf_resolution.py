from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pymupdf

from src.studio import server
from src.studio.document import new_score
from src.studio.pdf_resolution import dense_score_dpi


def page_with_staffs(pdf, gap, lines=5, width=595):
    page = pdf.new_page(width=width, height=842)
    for top in (80, 140):
        for i in range(lines):
            y = top + i * gap
            for x in (40, 96):
                page.draw_line((x, y), (x + 56, y), width=.3)


def test_resolution_respects_staff_spacing_sheet_selection_and_pixel_budget():
    with pymupdf.open() as pdf:
        page_with_staffs(pdf, 2.5)
        page_with_staffs(pdf, 4.8)
        page_with_staffs(pdf, 2.5, lines=6)
        page_with_staffs(pdf, 2.5, width=1400)
        data = pdf.tobytes()
    assert dense_score_dpi(data, ["1"], 16_000_000) == 400
    assert dense_score_dpi(data, ["1"], 12_000_000) == 350
    assert dense_score_dpi(data, ["2"], 16_000_000) is None
    assert dense_score_dpi(data, ["3"], 16_000_000) is None
    assert dense_score_dpi(data, ["1", "4"], 16_000_000) is None
    assert dense_score_dpi(b"invalid", [], 16_000_000) is None


def test_dense_scan_falls_back_after_empty_export(tmp_path, monkeypatch):
    with pymupdf.open() as pdf:
        page_with_staffs(pdf, 2.5)
        original = pdf.tobytes()
    workspace = SimpleNamespace(library=server.Library(tmp_path / "studio.db"), jobs={})
    sid = workspace.library.add(new_score(bars=2), {"origin": "Scan", "reviewed": True},
                                original, "application/pdf")
    previous = workspace.library.get(sid)
    attempts = []
    def engine(args, **kwargs):
        if "-save" in args:
            attempts.append(args)
            with ZipFile(Path(args[args.index("-output") + 1]) / "scan.omr", "w"):
                pass
        else:
            result = new_score() if len(attempts) == 2 else b"<score-partwise><part><measure/></part></score-partwise>"
            Path(args[-1]).with_suffix(".musicxml").write_bytes(result)

    monkeypatch.setattr(server.subprocess, "run", engine)
    server.scan(workspace, "trial", "engine", original, ".pdf", sid, options={"pages": ["1"]})
    job = workspace.jobs["trial"]
    assert job["status"] == "done", job
    assert len(attempts) == 2
    assert "org.audiveris.omr.image.ImageLoading.pdfResolution=400" in attempts[0]
    assert not any("pdfResolution=" in arg for arg in attempts[1])
    assert attempts[1][attempts[1].index("-sheets") + 1] == "1"
    saved = workspace.library.get(job["id"])
    assert saved["source"] == original and saved["xml"] != previous["xml"]
    restored = workspace.library.update(sid, saved["revision"], undo=True)
    assert restored["xml"] == previous["xml"]
    assert restored["meta"] == previous["meta"]
