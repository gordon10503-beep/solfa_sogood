"""Offer a reversible repair when a scan counts a courtesy signature as a bar."""
from math import isfinite


def _edge(bar, previous, following):
    """Check one staff part and return the incoming key and any suspect pitches."""
    if set(bar.attrib) != {"number", "width"}:
        return None
    boundary = previous.find("barline[@location='right']")
    if boundary is None or boundary.findtext("bar-style") != "light-light" or any(c.tag != "bar-style" for c in boundary):
        return None
    try:
        width, prior_width, next_width = (float(m.attrib["width"]) for m in (bar, previous, following))
    except (ValueError, KeyError):
        return None
    if not all(isfinite(w) and w > 0 for w in (width, prior_width, next_width)) or width >= min(prior_width / 4, next_width / 3):
        return None
    if not any(p.get("new-system") == "yes" or p.get("new-page") == "yes" for p in following.findall("print")):
        return None
    if any(c.tag not in {"note", "attributes"} for c in bar) or len(bar.findall("attributes")) != 1:
        return None
    attr = bar.find("attributes")
    if attr.attrib or [c.tag for c in attr] != ["key"] or bar[0] is not attr:
        return None
    key = attr[0]
    if key.attrib or [c.tag for c in key] != ["fifths"] or key.findtext("fifths") is None:
        return None
    # The next system must explicitly establish meter. A second key or a late
    # attributes block could override the signature we propose carrying over.
    opening = following.find("attributes")
    if (opening is None or following[0].tag != "print" or len(following.findall("attributes")) != 1
            or any(c.tag != "print" for c in list(following)[:list(following).index(opening)])
            or following.find("attributes/key") is not None or opening.find("time/beats") is None):
        return None
    # The export can mistake a digit or sharp in the courtesy signature for an
    # isolated note. Keep lyrics, ties, beams, ornaments and other marked music.
    notes = bar.findall("note")
    if len(notes) > 1 or any(n.find("pitch") is None or n.find("duration") is None or
            any(c.tag not in {"pitch", "duration", "voice", "type", "stem", "staff"} for c in n) for n in notes):
        return None
    return key.findtext("fifths"), notes


def candidates(root):
    if not any((s.text or "").startswith("Audiveris ") for s in root.iter("software")):
        return
    rows = [part.findall("measure") for part in root.findall("part")]
    if len(rows) < 3 or len({len(row) for row in rows}) != 1:
        return
    if any(bar.get("number") != str(i + 1) for row in rows for i, bar in enumerate(row)):
        return
    for i in range(1, len(rows[0]) - 1):
        if rows[0][i].find("attributes/key") is None:
            continue
        edges = [_edge(row[i], row[i-1], row[i+1]) for row in rows]
        if any(edge is None for edge in edges) or len({edge[0] for edge in edges}) != 1:
            continue
        affected = [pi for pi, (_, notes) in enumerate(edges) if notes]
        if len(affected) * 2 >= len(rows):
            continue
        yield i, affected


def remove_confirmed(root, index):
    if type(index) is not int or not any(i == index for i, _ in candidates(root)):
        raise ValueError("This bar no longer qualifies as a courtesy signature. Compare it with the PDF again.")
    for part in root.findall("part"):
        bars = part.findall("measure")
        bar = bars[index]
        following = bars[index+1].find("attributes")
        # MusicXML places keys after divisions and before time and clef.
        prefix = next((n for n, el in enumerate(following) if el.tag not in {"footnote", "level", "divisions"}), len(following))
        following.insert(prefix, bar.find("attributes/key"))
        part.remove(bar)
        for number, measure in enumerate(bars[index+1:], index+1):
            measure.set("number", str(number))
