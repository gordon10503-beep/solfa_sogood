"""Choose a bounded Audiveris render resolution for tightly engraved PDFs."""
from collections import defaultdict
from math import sqrt
from statistics import median

import pymupdf


def staff_spacing(page):
    """Find groups of five rules with shared endpoints (whole staves or individual bars)."""
    segments = defaultdict(set)
    for path in page.get_cdrawings():
        stroked = "s" in path["type"] and path.get("width", 0) <= 1.5
        filled = "f" in path["type"]
        for item in path["items"]:
            if stroked and item[0] == "l":
                (left, top), (right, bottom) = item[1:3]
            elif filled and item[0] == "re":
                left, top, right, bottom = item[1]
            else:
                continue
            if abs(bottom - top) > (1.2 if item[0] == "re" else .2) or abs(right - left) < 20:
                continue
            ends = tuple(sorted((round(left), round(right))))
            segments[ends].add(round((bottom + top) / 2, 1))

    staves = {}
    for rows in segments.values():
        ys = sorted(rows)
        for i in range(len(ys) - 4):
            gap = (ys[i + 4] - ys[i]) / 4
            if not 1.5 <= gap <= 9:
                continue
            if i and ys[i] - ys[i - 1] < 1.5 * gap:
                continue
            if i + 5 < len(ys) and ys[i + 5] - ys[i + 4] < 1.5 * gap:
                continue
            if all(abs(ys[j + 1] - ys[j] - gap) <= .25 for j in range(i, i + 4)):
                staves[ys[i]] = gap
    return median(staves.values()) if len(staves) >= 2 else None


def dense_score_dpi(data, pages, max_pixels):
    """A book has one DPI. Sample its layout and bound cost on its largest selected page."""
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            selected = [int(p) - 1 for p in pages] if pages else range(len(pdf))
            if not selected:
                return None
            largest = max(pdf.page_cropbox(i).get_area() for i in selected)
            if largest <= 0:
                return None
            # Bound path extraction on large books, while including both ends.
            sample = {selected[round((len(selected) - 1) * i / 4)] for i in range(5)}
            spacings = [gap for i in sorted(sample) if (gap := staff_spacing(pdf[i]))]
    except (ValueError, RuntimeError, IndexError):
        return None
    if not spacings or median(spacings) * 300 / 72 >= 14:
        return None
    # Aim for 20 px per staff space, up to 400 DPI. Avoid trivial increases.
    limit = min(400, 20 * 72 / median(spacings), 72 * sqrt(max_pixels / largest))
    dpi = 25 * int(limit / 25)
    return dpi if dpi >= 325 else None
