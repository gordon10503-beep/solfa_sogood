"""Build an offline answer book for the private, source-checked benchmark passages."""
import argparse
from collections import defaultdict
from fractions import Fraction
from html import escape
from itertools import groupby
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from benchmarks.replay import CASES, load_reference, note_key


def vocal_excerpts(folder, ref):
    """Export only contiguous, checked single-line parts with known printed meters."""
    case = ref["case"]
    if case not in ("grow", "middle"):
        return []
    meter, unit, fifths = (6, 8, -3) if case == "grow" else (4, 4, 6)
    by_part = defaultdict(list)
    for bar in ref["passages"]:
        by_part[bar["part"]].append(bar)
    files = []
    for part, bars in by_part.items():
        indexed = enumerate(sorted(bars, key=lambda b: b["bar"]))
        for _, segment in groupby(indexed, key=lambda pair: pair[1]["bar"]-pair[0]):
            sequence = [b for _, b in segment]
            start, end = sequence[0]["bar"], sequence[-1]["bar"]
            name = sequence[0]["partName"]
            root = ET.Element("score-partwise", version="4.0")
            ET.SubElement(ET.SubElement(root, "work"), "work-title").text = f"{case} · {name} · bars {start}–{end}"
            declaration = ET.SubElement(ET.SubElement(root, "part-list"), "score-part", id="P1")
            ET.SubElement(declaration, "part-name").text = name
            track = ET.SubElement(root, "part", id="P1")
            for b in sequence:
                bar = ET.SubElement(track, "measure", number=str(b["bar"]))
                if b["bar"] == start:
                    attr = ET.SubElement(bar, "attributes")
                    ET.SubElement(attr, "divisions").text = "96"
                    ET.SubElement(ET.SubElement(attr, "key"), "fifths").text = str(fifths)
                    time = ET.SubElement(attr, "time")
                    ET.SubElement(time, "beats").text = str(meter)
                    ET.SubElement(time, "beat-type").text = str(unit)
                    clef = ET.SubElement(attr, "clef")
                    ET.SubElement(clef, "sign").text = "G"
                    ET.SubElement(clef, "line").text = "2"
                def add(pitch, length):
                    ticks = length*96
                    if ticks.denominator != 1 or ticks <= 0:
                        raise ValueError("Unsupported or overlapping vocal event")
                    note = ET.SubElement(bar, "note")
                    if pitch:
                        _, step, alter, octave, _ = note_key(0, pitch, length)
                        tag = ET.SubElement(note, "pitch")
                        ET.SubElement(tag, "step").text = step
                        if alter:
                            ET.SubElement(tag, "alter").text = str(alter)
                        ET.SubElement(tag, "octave").text = str(octave)
                    else:
                        ET.SubElement(note, "rest")
                    ET.SubElement(note, "duration").text = str(ticks)
                    if case == "grow" and pitch == "Eb5" and b["bar"] in range(54,62):
                        kinds = (["stop"] if b["bar"] > 54 else []) + (["start"] if b["bar"] < 61 else [])
                        for kind in kinds:
                            ET.SubElement(note, "tie", type=kind)
                        marks = ET.SubElement(note, "notations")
                        for kind in kinds:
                            ET.SubElement(marks, "tied", type=kind)
                pos = Fraction(0)
                for onset, pitch, length in b["events"]:
                    onset, length = Fraction(onset), Fraction(length)
                    if onset != pos:
                        add(None, onset-pos)
                    add(pitch, length)
                    pos = onset+length
                limit = Fraction(meter*4, unit)
                if case == "grow" and b["bar"] == 1:
                    bar.set("implicit", "yes")
                elif limit != pos:
                    add(None, limit-pos)
            file = folder/f"{case}-part{part+1}-bars{start}-{end}.musicxml"
            ET.indent(root)
            file.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
            files.append(file.name)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", type=Path, default=Path("data/benchmark-references"))
    args = parser.parse_args()
    output = args.references / "answers"
    output.mkdir(exist_ok=True)
    html = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Choir benchmark answers</title><style>body{font:1rem/1.55 system-ui;color:#1b253d;margin:2rem auto;padding:0 1rem;max-width:72rem}summary{cursor:pointer;padding:.5rem}td,th{padding:.35rem .7rem;text-align:left;vertical-align:top;border-bottom:1px solid #ddd}table{border-collapse:collapse}a{color:#3248a8}</style><main><h1>Choir benchmark answers</h1><p>Each entry gives onset, sounding pitch and duration in quarter notes. Simultaneous pitches share an onset. Empty bars were checked for silence. Unlisted bars and parts are outside the reference.</p>']
    for digest, (case, _) in CASES.items():
        ref, _ = load_reference(args.references/(case+".json"), digest)
        html.append(f'<h2>{escape(case.title())}</h2><p>{escape(ref["scope"])}</p>')
        for file in vocal_excerpts(output, ref):
            html.append(f'<p><a href="{file}" download>{escape(file)}</a></p>')
        for name in ref["expectedParts"]:
            rows = [b for b in ref["passages"] if b["partName"] == name]
            if not rows:
                continue
            html.append(f'<details><summary>{escape(name)} · {len(rows)} checked bars</summary><table><tr><th>Page<th>Bar<th>Onset / pitch / length')
            for bar in sorted(rows,key=lambda b:b["bar"]):
                notes = " · ".join(" / ".join(map(str,event)) for event in bar["events"])
                html.append(f'<tr><td>{bar["page"]}<td>{bar["bar"]}<td>{escape(notes) or "Silent"}')
            html.append('</table></details>')
    html.append('<p>MusicXML excerpts preserve measured pitch and rhythm. Rests fill verified gaps. Articulation, phrasing, ties and repeats need separate review. The checked final tie chain in Grow for Me is included.</p></main></html>')
    (output/"index.html").write_text("\n".join(html), encoding="utf-8")


if __name__ == "__main__":
    main()
