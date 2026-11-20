"""Choose Audiveris recognition settings from notation visible in the input."""
from collections import Counter

import pymupdf


def mixed_note_sizes(sizes):
    """Require repeated evidence of two note sizes within one staff-sized band."""
    if not sizes:
        return False
    normal, count = sizes.most_common(1)[0]
    return count >= 6 and sum(n for size, n in sizes.items()
                              if .55 * normal <= size <= .82 * normal) >= 3


def pdf_has_small_heads(data, pages):
    # Only use fonts whose private-use characters are known SMuFL noteheads.
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for number in pages or range(1, len(pdf) + 1):
            page = pdf[int(number)-1]
            bands = {}
            for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        if span["font"].split("+")[-1] not in ("Leland", "Bravura"):
                            continue
                        count = sum(0xE0A2 <= ord(ch) <= 0xE0A4 for ch in span["text"])
                        if count:
                            y = span["origin"][1]
                            # Overlap windows to avoid a hard cut through a staff.
                            for offset in (0, 12):
                                band = (offset, int((y+offset)//24))
                                bands.setdefault(band, Counter())[round(span["size"], 1)] += count
            if any(mixed_note_sizes(sizes) for sizes in bands.values()):
                return True
    return False


def recognition_flags(mode, data, ext, pages):
    if mode == "auto":
        try:
            enabled = ext == ".pdf" and pdf_has_small_heads(data, pages)
        except (ValueError, RuntimeError, IndexError):
            enabled = False
    else:
        enabled = mode == "on"
    if enabled:
        return ["-constant", "org.audiveris.omr.sheet.ProcessingSwitches.smallHeads=true"]
    if mode == "off":
        return ["-constant", "org.audiveris.omr.sheet.ProcessingSwitches.smallHeads=false"]
    return []

def experiment_flags(font=None, quality=None):
    flags = []
    for key, value, allowed in (
        ("org.audiveris.omr.ui.symbol.MusicFont.defaultMusicFamily", font, {"Leland", "Bravura"}),
        ("org.audiveris.omr.sheet.Profiles.defaultQuality", quality, {"Standard", "Synthetic", "Poor"}),
    ):
        if value is not None:
            if value not in allowed:
                raise ValueError("Unsupported Audiveris experiment setting.")
            flags.extend(["-constant", f"{key}={value}"])
    return flags


def page_evidence(page):
    """Propose evidence only for a user-requested trial on this specific page."""
    from .pdf_resolution import staff_spacing
    votes = Counter()
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text("dict", flags=flags)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                family = span["font"].split("+")[-1]
                votes[family] += sum(0xE0A0 <= ord(c) <= 0xE0BF for c in span["text"])
    positive = [name for name, count in votes.items() if count]
    font = positive[0] if len(positive) == 1 and votes[positive[0]] >= 8 and positive[0] in ("Bravura", "Leland") else None
    metadata = page.parent.metadata or {}
    creator = " ".join(str(metadata.get(key, "")) for key in ("creator","producer")).casefold()
    engraving_evidence = font is not None or any(name in creator for name in ("musescore","lilypond","sibelius","dorico","finale"))
    quality = "Synthetic" if engraving_evidence and not page.get_image_info() and staff_spacing(page) is not None else None
    return font, quality
