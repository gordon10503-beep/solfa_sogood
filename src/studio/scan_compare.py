"""Descriptive MusicXML comparisons for scan trials and full-page candidates."""
from collections import Counter
from fractions import Fraction

from .document import inspect, read_xml


def describe(data, page=None, page_count=None):
    """Use exported breaks only when every part has the expected number of pages."""
    root = read_xml(data)
    names = {p.get("id"): p.findtext("part-name", "") for p in root.findall("part-list/score-part")}
    events, parts = Counter(), []
    for pi, part in enumerate(root.findall("part")):
        divisions, staves, current_page, count = Fraction(1), 1, 1, 0
        for mi, measure in enumerate(part.findall("measure")):
            if mi and measure.find("print[@new-page='yes']") is not None:
                current_page += 1
            included = page is None or current_page == page
            pos = previous = Fraction(0)
            for node in measure:
                if node.tag == "attributes":
                    divisions = Fraction(node.findtext("divisions", str(divisions)))
                    staves = max(staves, int(node.findtext("staves", "1")))
                elif node.tag in ("note", "forward", "backup"):
                    duration = Fraction(node.findtext("duration", "0")) / divisions
                    if node.tag == "backup":
                        pos -= duration
                    elif node.tag == "forward":
                        pos += duration
                    elif node.find("grace") is None:
                        if node.find("chord") is None:
                            previous = pos
                            pos += duration
                        pitch = node.find("pitch")
                        if pitch is not None and included:
                            key = (pi, count, previous, node.findtext("staff", "1"), pitch.findtext("step"),
                                   Fraction(pitch.findtext("alter", "0")), pitch.findtext("octave"), duration)
                            events[key] += 1
            count += int(included)
        if page is not None and current_page != page_count:
            return None
        parts.append({"name": names.get(part.get("id"), ""), "staves": staves, "bars": count})
    return parts, events


def compare(reference, candidate):
    rp, revents = reference
    cp, cevents = candidate
    common = sum((revents & cevents).values())
    def examples(diff):
        return [{"part":k[0]+1, "bar":k[1]+1, "onset":str(k[2]), "staff":k[3],
                 "pitch":k[4]+({"0":"", "1":"♯", "-1":"♭"}.get(str(k[5]), f"({k[5]})"))+k[6],
                 "duration":str(k[7]), "count":count} for k,count in sorted(diff.items())[:5]]
    return {"baselineParts": rp, "candidateParts": cp,
            "partCountMatches": len(rp) == len(cp),
            "partNamesAndStavesMatch": [(p["name"].strip().casefold(), p["staves"]) for p in rp] ==
                                       [(p["name"].strip().casefold(), p["staves"]) for p in cp],
            "barCountsMatch": [p["bars"] for p in rp] == [p["bars"] for p in cp],
            "matched": common, "baselineOnly": revents.total()-common, "candidateOnly": cevents.total()-common,
            "baselineExamples":examples(revents-cevents), "candidateExamples":examples(cevents-revents)}


def structural_checks(data):
    root = read_xml(data)
    info = inspect(root)
    ids = [p.get("id") for p in root.findall("part")]
    declared = [p.get("id") for p in root.findall("part-list/score-part")]
    issues = Counter(i.get("code") or i["message"].split(":")[0] for i in info["issues"])
    return {"validPartIds": ids == declared and len(ids) == len(set(ids)),
            "alignedBarNumbers": len({tuple(m.get("number") for m in p.findall("measure"))
                                       for p in root.findall("part")}) == 1,
            "inspectionFindings": dict(issues)}
