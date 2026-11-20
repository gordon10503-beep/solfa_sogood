"""Explicit recognition settings and conservative SATB book assembly."""
import re
import shutil
import zipfile
from xml.etree import ElementTree as ET


def selected_pages(value):
    value = str(value or "").strip()
    if not value:
        return []
    if not re.fullmatch(r"\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*", value):
        raise ValueError("Use page numbers such as 1-4, 6. Leave blank for all pages.")
    pages = set()
    for token in value.split(","):
        bounds = [int(x) for x in token.strip().split("-")]
        start, end = bounds[0], bounds[-1]
        if start < 1 or end < start or end > 10000:
            raise ValueError("Page ranges must be increasing, between 1 and 10000.")
        pages.update(range(start, end + 1))
    return [str(p) for p in sorted(pages)]


def repair_empty_run_tables(path):
    """Represent zero-column glyphs by one blank column for Audiveris's JAXB reader."""
    empty = re.compile(rb'<run-table orientation="VERTICAL" width="0" height="([0-9]+)"\s*/>')
    replacements = {}
    with zipfile.ZipFile(path) as source:
        for name in source.namelist():
            if re.fullmatch(r"sheet#\d+/sheet#\d+\.xml", name):
                sheet, count = empty.subn(rb'<run-table orientation="VERTICAL" width="1" height="\1"><runs/></run-table>', source.read(name))
                if count:
                    replacements[name] = sheet
        if not replacements:
            return
        temporary = path.with_suffix(".fixed.tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
            for entry in source.infolist():
                target.writestr(entry, replacements[entry.filename] if entry.filename in replacements else source.read(entry))
    temporary.replace(path)


def repair_satb_book(path, layout="satb-piano"):
    """Only for an explicitly selected five-part SATB + piano layout.

    Refuse mismatched systems rather than deleting or guessing voice content.
    Keep the untouched OMR book for investigation.
    """
    names = {"satb-piano": ("Soprano", "Alto", "Tenor", "Bass", "Piano"), "satb": ("Soprano", "Alto", "Tenor", "Bass"), "piano": ("Piano",)}[layout]
    counts = [2 if name == "Piano" else 1 for name in names]
    with zipfile.ZipFile(path) as source:
        root = ET.fromstring(source.read("book.xml"))
        systems = root.findall("sheet/page/system")
        if not systems or any([len(p.findall("staff-configuration")) for p in s.findall("part")] != counts for s in systems):
            raise ValueError("Selected ensemble does not match the detected staves in every system. Retry Automatic, or correct staff grouping in Audiveris.")
        for system in systems:
            for i, part in enumerate(system.findall("part")):
                part.set("logical-id", str(i+1))
        scores = root.findall("score")
        if len(scores) != 1:
            raise ValueError("The SATB preset currently supports a single movement. Use Automatic for this book.")
        score = scores[0]
        for part in score.findall("logical-part"): score.remove(part)
        for i,name in enumerate(names):
            count = counts[i]
            part = ET.Element("logical-part", {"id": str(i+1), "staff-count": str(count), "name": name})
            for _ in range(count): ET.SubElement(part, "staff-configuration", {"line-count": "5"})
            score.insert(i,part)
        temporary = path.with_suffix(".tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as output:
            for entry in source.infolist():
                output.writestr(entry, ET.tostring(root, encoding="utf-8", xml_declaration=True) if entry.filename == "book.xml" else source.read(entry.filename))
    shutil.copy2(path, path.with_suffix(".original.omr"))
    temporary.replace(path)
