"""Exact MusicXML duration/tempo playback, independent of engraving guesses."""
from bisect import bisect_right


def measure_order(root, count):
    """Expand ordinary forward/backward repeats and numbered endings.

    D.S., D.C., coda and nested repeats are flagged by document inspection.
    Bound expansions so malformed repetition cannot hang the local server.
    """
    measures = root.find("part").findall("measure")
    order, repeated = [], {}
    seen_forwards = set()
    index, start, pass_number, ending = 0, 0, 1, None
    steps = 0
    while index < count:
        steps += 1
        if steps > count * 16 + 32:
            raise ValueError("Repeat navigation is too complex. Simplify repeats in MusicXML.")
        m = measures[index] if index < len(measures) else None
        if m is not None:
            if m.find("barline/repeat[@direction='forward']") is not None:
                if index not in seen_forwards:
                    pass_number = 1
                    seen_forwards.add(index)
                start = index
            for e in m.findall("barline/ending"):
                if e.get("type") == "start":
                    try: ending = {int(n.strip()) for n in e.get("number", "1").split(",")}
                    except ValueError: ending = None
        if ending is None or pass_number in ending:
            order.append(index)
        backward = m.find("barline/repeat[@direction='backward']") if m is not None else None
        if backward is not None:
            times = max(1, min(8, int(backward.get("times", "2"))))
            done = repeated.get(index, 1)
            if done < times:
                repeated[index] = done + 1
                pass_number = done + 1
                index = start
                ending = None
                continue
            start = index + 1
        if m is not None and any(e.get("type") in ("stop", "discontinue") for e in m.findall("barline/ending")):
            ending = None
        index += 1
    return order


def build_playback(root, info):
    parts = info["parts"]
    count = max(len(p["measures"]) for p in parts)
    order = measure_order(root, count)
    notes_by_bar = {}
    for n in info["notes"].values():
        notes_by_bar.setdefault(n["measure"], []).append(n)
    q = 0.
    quarter_events, measure_times, tempos, ties = [], [], {0.: 120.}, {}
    tempo_on_entry = {}
    current_tempo = tempos[0.]
    for position, mi in enumerate(order):
        bars = [p["measures"][mi] for p in parts if mi < len(p["measures"])]
        expected = max(b["length"] for b in bars)
        extent = max(b["extent"] for b in bars)
        pickup = mi == 0 or all(b["implicit"] for b in bars)
        length = extent if pickup and 0 < extent < expected else max(expected, extent)
        measure_times.append({"id": f"ss-measure-{mi}", "qstamp": q, "measure": mi})
        # A repeat can begin several bars after the tempo was printed. Restore
        # its inherited pace, even if the first ending changed it mid-phrase.
        if position and mi <= order[position - 1] and mi in tempo_on_entry:
            current_tempo = tempo_on_entry[mi]
            tempos[q] = current_tempo
        tempo_on_entry.setdefault(mi, current_tempo)
        # Most MusicXML puts tempo on part 1; other parts can supply missing
        # markings. Conflicting values at the same position use the top part.
        local_tempos = {}
        for bar in bars:
            for t in bar["tempos"]:
                local_tempos.setdefault(max(0, t["offset"]), t["bpm"])
        for offset in sorted(local_tempos):
            current_tempo = local_tempos[offset]
            tempos[q + min(offset, length)] = current_tempo
        for n in notes_by_bar.get(mi, []):
            if not n["pitched"] or n["grace"] or n["duration"] <= 0:
                continue
            onset = q + n["offset"]
            key = (n["part"], n["staff"], n["voice"], n["midi"])
            pending = ties.pop(key, None)
            event = {"id": n["id"], "part": n["part"], "measure": mi,
                     "pitch": n["midi"], "start": onset, "end": onset+n["duration"]}
            end = event["end"]
            if n["tieStop"] and pending and abs(pending[1] - onset) < 1e-5:
                event = pending[0]
                event["end"] = end
            else:
                quarter_events.append(event)
            if n["tieStart"]:
                bar = parts[n["part"]]["measures"][mi]
                # Another scanned part may overfill this measure. Match an
                # explicit continuation across the padded ensemble boundary.
                match_at = end
                if (position + 1 < len(order) and order[position+1] == mi+1
                        and abs(end-q-bar["extent"]) < 1e-5
                        and abs(bar["extent"]-bar["length"]) < 1e-5):
                    match_at = q + length
                ties[key] = (event, match_at)
        q += length
    positions = sorted(tempos)
    elapsed, seconds = 0., []
    for i, pos in enumerate(positions):
        if i: elapsed += (pos - positions[i-1]) * 60 / tempos[positions[i-1]]
        seconds.append(elapsed)
    def at(quarter):
        i = max(0, bisect_right(positions, quarter) - 1)
        return seconds[i] + (quarter - positions[i]) * 60 / tempos[positions[i]]
    events = [{"id": e["id"], "part": e["part"], "measure": e["measure"], "pitch": e["pitch"],
               "time": at(e["start"]), "duration": at(e["end"]) - at(e["start"])}
              for e in quarter_events]
    for m in measure_times: m["time"] = at(m["qstamp"])
    points = sorted({0., q, *positions, *(m["qstamp"] for m in measure_times),
                     *(e["start"] for e in quarter_events), *(e["end"] for e in quarter_events)})
    timeline = [{"qstamp": p, "tstamp": at(p)*1000, "tempo": tempos[positions[max(0, bisect_right(positions,p)-1)]]} for p in points]
    return {"events": sorted(events, key=lambda e: (e["time"],e["part"],e["id"])),
            "measureTimes": measure_times, "timeline": timeline,
            "duration": at(q), "baseTempo": tempos[0.]}
