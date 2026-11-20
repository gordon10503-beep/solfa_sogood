"""Recover omitted opening meters using positioned SMuFL glyphs in a PDF."""
import xml.etree.ElementTree as ET
import re

from .document import read_xml, xml_bytes


def recover_opening_tempo(output, pdf_data, page_number):
    """Repair a dropped metronome dot when the original beat unit and numeral also match."""
    import pymupdf
    root = read_xml(output)
    bar = root.find("part/measure")
    if bar is None:
        return output
    directions = []
    for el in bar:
        if el.tag in ("note", "forward", "backup"):
            break
        if el.find("direction-type/metronome") is not None:
            directions.append(el)
    if len(directions) != 1:
        return output
    direction = directions[0]
    mark = direction.find("direction-type/metronome")
    bpm = mark.findtext("per-minute", "").strip()
    if (not re.fullmatch(r"[1-9]\d{0,2}", bpm) or mark.findtext("beat-unit") != "quarter"
            or len(mark) != 2 or direction.find("offset") is not None):
        return output
    sound = direction.find("sound")
    if sound is not None and sound.get("tempo", bpm) != bpm:
        return output
    try:
        with pymupdf.open(stream=pdf_data, filetype="pdf") as pdf:
            pg = pdf[page_number-1]
            spans = [s for b in pg.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]
                     for line in b.get("lines", []) for s in line["spans"]]
    except (RuntimeError, ValueError, IndexError):
        return output
    clefs = [s for s in spans if s["font"].split("+")[-1] in ("Leland", "Bravura")
             and any(c in s["text"] for c in "\ue050\ue05c\ue062")]
    if not clefs:
        return output
    clef = min(clefs, key=lambda s:s["origin"][1])
    x, y = clef["origin"]
    size = clef["size"]
    matches = [s for s in spans if s["font"].split("+")[-1] in ("LelandText", "BravuraText")
               and s["text"] in ("\ueca5\uecb7", "\ueca6\uecb7")
               and x-size <= s["origin"][0] <= x+2*size and y-4*size <= s["origin"][1] < y]
    if len(matches) != 1:
        return output
    glyph = matches[0]
    if not any(abs(s["origin"][1]-glyph["origin"][1]) < 1 and
               abs(s["origin"][0]-glyph["bbox"][2]) < 2 and
               re.fullmatch(r"\s*=\s*" + bpm + r"\s*", s["text"]) for s in spans):
        return output
    mark.insert(1, ET.Element("beat-unit-dot"))
    if sound is not None:
        sound.set("tempo", f"{int(bpm)*1.5:g}")
    return xml_bytes(root)


def _printed_signature(clef, signs, attacks):
    x, y, size = clef
    right = min((ax for ax, ay in attacks if ax > x and abs(ay - y) < size),
                default=x + 4 * size)
    symbols = [(sx, sy, value) for sx, sy, value in signs
               if x < sx < min(right, x + 4 * size) and abs(sy - y) < size]
    if len(symbols) == 1 and symbols[0][2] in (0xE08A, 0xE08B):
        sx, _, value = symbols[0]
        return (sx, (4, 4, "common") if value == 0xE08A else (2, 2, "cut"))

    # PDF producers may put every digit into its own line or span. Group by
    # printed baseline, then verify that the two rows are actually stacked.
    if not 2 <= len(symbols) <= 4 or any(value > 0xE089 for _, _, value in symbols):
        return None
    rows = []
    for sx, sy, value in sorted(symbols, key=lambda s: s[1]):
        if not rows or sy - rows[-1][0][1] > size * .06:
            rows.append([])
        rows[-1].append((sx, sy, value - 0xE080))
    if len(rows) != 2 or any(len(row) > 2 for row in rows):
        return None
    if not size * .2 <= rows[1][0][1] - rows[0][0][1] <= size * .85:
        return None
    values, centers = [], []
    for row in rows:
        row.sort()
        if len(row) == 2 and not size * .1 < row[1][0] - row[0][0] < size * .7:
            return None
        centers.append(sum(glyph[0] for glyph in row) / len(row))
        values.append(int("".join(str(glyph[2]) for glyph in row)))
    if abs(centers[0] - centers[1]) > size * .3:
        return None
    beats, unit = values
    if 1 <= beats <= 32 and unit in (1, 2, 4, 8, 16, 32):
        return (centers[0], (beats, unit, None))
    return None


def _opening_signature(page, staff_count):
    import pymupdf
    clefs, signs, attacks = [], [], []
    flags = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text("rawdict", flags=flags)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["font"].split("+")[-1] not in {"Leland", "Bravura"}:
                    continue
                for char in span["chars"]:
                    value = ord(char["c"])
                    x, y = char["origin"]
                    if 0xE050 <= value <= 0xE057 or value in (0xE05C, 0xE05D) or 0xE062 <= value <= 0xE066:
                        clefs.append((x, y, span["size"]))
                    elif 0xE0A0 <= value <= 0xE0BF or 0xE4E1 <= value <= 0xE4EF:
                        attacks.append((x, y))
                    elif 0xE080 <= value <= 0xE09F:
                        signs.append((x, y, value))
    if not clefs or staff_count < 2:
        return None
    left, _, size = min(clefs, key=lambda c: c[1])
    starts = sorted((c for c in clefs if abs(c[0] - left) < size / 2), key=lambda c: c[1])[:staff_count]
    if len(starts) != staff_count:
        return None
    if any(not size < b[1] - a[1] <= 8 * size for a, b in zip(starts, starts[1:])):
        return None
    votes = [_printed_signature(clef, signs, attacks) for clef in starts]
    if any(vote is None for vote in votes):
        return None
    first_x, signature = votes[0]
    if all(vote == signature and abs(x - first_x) < size / 4 for x, vote in votes):
        return signature
    return None


def opening_meter(page):
    signature = _opening_signature(page, 2)
    return signature[:2] if signature else None


def recover_opening_meter(output, pdf_data, page_number=1):
    root = read_xml(output)
    first = [part.find("measure") for part in root.findall("part")]
    if not first or any(m is None for m in first):
        return output, None
    missing = [m for m in first if m.find("attributes/time") is None]
    if not missing:
        return output, None
    import pymupdf
    try:
        staff_count = sum(int(m.findtext("attributes/staves", "1")) for m in first)
        with pymupdf.open(stream=pdf_data, filetype="pdf") as pdf:
            signature = _opening_signature(pdf[page_number - 1], staff_count)
    except (RuntimeError, ValueError, IndexError):
        return output, None
    if signature is None:
        return output, None
    beats, unit, symbol = signature
    for m in first:
        for existing in m.findall("attributes/time"):
            if ([e.text for e in existing.findall("beats")] != [str(beats)]
                    or [e.text for e in existing.findall("beat-type")] != [str(unit)]):
                return output, None

    for measure in missing:
        attributes = measure.find("attributes")
        if attributes is None:
            attributes = ET.Element("attributes")
            measure.insert(0, attributes)
        time = ET.Element("time", {"symbol": symbol} if symbol else {})
        ET.SubElement(time, "beats").text = str(beats)
        ET.SubElement(time, "beat-type").text = str(unit)
        index = next((i for i, el in enumerate(attributes)
                      if el.tag not in ("footnote", "level", "divisions", "key")), len(attributes))
        attributes.insert(index, time)
    return xml_bytes(root), (beats, unit)
