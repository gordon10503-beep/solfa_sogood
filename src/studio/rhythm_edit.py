"""Direct duration correction of a note or rest in a single rhythmic line."""
from fractions import Fraction
from xml.etree import ElementTree as ET

from .document import DURATIONS, inspect, read_xml, xml_bytes


def resize_note(data, nid, unit, dotted=False):
    if unit not in DURATIONS or type(dotted) is not bool:
        raise ValueError("Choose a standard note length.")
    root = read_xml(data)
    info = inspect(root)
    target = info["notes"].get(nid)
    if target is None:
        raise ValueError("Select the note again.")
    pi, mi = target["part"], target["measure"]
    bar = root.findall("part")[pi].findall("measure")[mi]
    notes = bar.findall("note")
    note = notes[target["index"]]
    lanes = {(n.findtext("staff", "1"), n.findtext("voice", "1")) for n in notes}
    if len(lanes) != 1 or any(bar.find(tag) is not None for tag in ("backup", "forward")):
        raise ValueError("Use the MusicXML editor to adjust overlapping voices together.")
    if any(note.find(tag) is not None for tag in
           ("chord", "tie", "notations/tied", "time-modification", "grace", "cue", "unpitched")):
        raise ValueError("This rhythm is linked. Edit its group together.")
    index = target["index"]
    if index+1 < len(notes) and notes[index+1].find("chord") is not None:
        raise ValueError("Edit the chord's durations together in MusicXML.")
    if note.find("beam") is not None and note.findtext("type") != unit:
        raise ValueError("This change needs new beams. Edit the beam group together in MusicXML.")
    if note.find("duration") is None or target["duration"] <= 0:
        raise ValueError("This note has no reliable timing.")
    # Recover the divisions active at this note, including mid-bar changes.
    divisions = round(int(note.findtext("duration")) / target["duration"])
    length = Fraction(DURATIONS[unit]) * (Fraction(3, 2) if dotted else 1)
    ticks = length * divisions
    if ticks.denominator != 1:
        raise ValueError("This length is smaller than the score's timing resolution.")
    timing = info["parts"][pi]["measures"][mi]
    delta = float(length) - target["duration"]
    if delta > 0 and timing["extent"] + delta > timing["length"] + 1e-6:
        raise ValueError("That length exceeds the bar. Shorten the incorrect note or rest first.")
    note.find("duration").text = str(ticks.numerator)
    rest = note.find("rest")
    if rest is not None:
        rest.attrib.pop("measure", None)
    for dot in note.findall("dot"):
        note.remove(dot)
    kind = note.find("type")
    if kind is None:
        kind = ET.Element("type")
        pos = next((i for i, el in enumerate(note) if el.tag in
                    ("accidental", "stem", "notehead", "staff", "beam", "notations", "lyric")), len(note))
        note.insert(pos, kind)
    kind.text = unit
    if dotted:
        note.insert(list(note).index(kind)+1, ET.Element("dot"))
    return xml_bytes(root)
