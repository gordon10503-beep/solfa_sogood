from contextlib import nullcontext
from unittest.mock import Mock, patch

import pytest

from src.studio.document import read_xml
from src.studio.pdf_meter import opening_meter, recover_opening_meter


def page_with_staves(*staves):
    # Each glyph is in a separate PDF text line, as can happen with subset fonts.
    lines = []
    for i, signs in enumerate(staves):
        y = 100 + 50 * i
        glyphs = [(0xE052 if i == 0 else 0xE062, 30, y)]
        glyphs.extend((code, 50 + dx, y + dy) for code, dx, dy in signs)
        for code, x, baseline in reversed(glyphs):
            span = {"font": "SUBSET+Bravura", "size": 20,
                    "chars": [{"origin": (x, baseline), "c": chr(code)}]}
            lines.append({"spans": [span]})
    return Mock(get_text=Mock(return_value={"blocks": [{"lines": lines}]}))


TWELVE_EIGHT = [(0xE081, 0, -10), (0xE082, 7, -9.8), (0xE088, 3.5, 0)]
THREE_EIGHT = [(0xE083, 0, -10), (0xE088, 0, 0)]


def test_numeric_rows_reconstructed_from_separate_lines():
    assert opening_meter(page_with_staves(TWELVE_EIGHT, TWELVE_EIGHT)) == (12, 8)


@pytest.mark.parametrize("other", [
    THREE_EIGHT,
    TWELVE_EIGHT + [(0xE0A4, -2, 0)],  # note before time signature
    TWELVE_EIGHT + [(0xE08D, 4, -10)],  # additive meter
    [(0xE081, 0, -10), (0xE082, 7, -10), (0xE088, 14, 0)],  # unstacked rows
])
def test_ambiguous_or_conflicting_print_abstains(other):
    assert opening_meter(page_with_staves(TWELVE_EIGHT, other)) is None


def score(existing_beats, existing_unit):
    return f"""<score-partwise><part id="a"><measure><attributes>
    <time print-object="no"><beats>{existing_beats}</beats><beat-type>{existing_unit}</beat-type></time>
    </attributes></measure></part><part id="b"><measure/></part></score-partwise>""".encode()


@pytest.mark.parametrize(("glyph", "beats", "unit", "symbol"),
                         [(0xE08A, 4, 4, "common"), (0xE08B, 2, 2, "cut")])
def test_fills_only_missing_meter_and_keeps_printed_symbol(glyph, beats, unit, symbol):
    page = page_with_staves(*([[(glyph, 0, 0)]] * 2))
    with patch("pymupdf.open", return_value=nullcontext([page])):
        output, meter = recover_opening_meter(score(beats, unit), b"pdf")
    assert meter == (beats, unit)
    original, recovered = read_xml(output).findall("part/measure/attributes/time")
    assert original.attrib == {"print-object": "no"}
    assert recovered.get("symbol") == symbol
    assert recovered.findtext("beats") == str(beats)
    assert recovered.findtext("beat-type") == str(unit)


def test_conflicting_recognized_or_third_printed_meter_preserves_xml():
    original = score(6, 8)
    page = page_with_staves(TWELVE_EIGHT, TWELVE_EIGHT)
    with patch("pymupdf.open", return_value=nullcontext([page])):
        assert recover_opening_meter(original, b"pdf") == (original, None)

    original = score(12, 8).replace(b'</score-partwise>', b'<part id="c"><measure/></part></score-partwise>')
    page = page_with_staves(TWELVE_EIGHT, TWELVE_EIGHT, THREE_EIGHT)
    with patch("pymupdf.open", return_value=nullcontext([page])):
        assert recover_opening_meter(original, b"pdf") == (original, None)
