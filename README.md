# solfa_sogood

solfa_sogood is a local, browser-based music workspace for reading, checking, composing and rehearsing scores. Solfa Studio combines editable MusicXML notation with the original imported PDF, so lyrics and markings remain visible while you review recognition.

## Get started

On Windows, install Python and double-click **Start Studio.cmd**. The launcher creates a virtual environment, installs the Studio dependencies and opens the local workspace at `http://127.0.0.1:8873`.

To install and run manually from PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-studio.txt
.venv\Scripts\python.exe -m src.studio.server
```

Use `--port 8874` to choose another port or `--data-dir PATH` to use another library. MusicXML reading and playback work locally. PDF and image recognition additionally require [Audiveris](https://github.com/Audiveris/audiveris) installed and available on PATH, or configured using `AUDIVERIS_CMD`.

## Features

- **Read:** import MusicXML/MXL and scanned PDFs or images; show movable-do, fixed-do or note names such as C4 above the digital notation. View the original PDF alongside the recognition, with one- or two-page layouts and selectable scrolling direction.
- **Practice:** play individual parts with layered sampled Piano, Flute, Strings, Organ or Bell sounds; adjust mix, tempo and volume; follow the current digital bar; use the metronome and scrollable keyboard.
- **Compose:** start a score, enter notes with the visual composer, and edit supported notes and bars. Advanced MusicXML editing and export are also available.
- **Check score:** compare the original and recognized notation, inspect structural warnings, and mark a score reviewed. Original PDFs retain their filenames and support saved pen and highlighter annotations.
- **Organize:** group scores into collections, bookmark bars, and use the score menu or right-click to rename, duplicate, export, share, or move scores to trash.
- **Conductor preview:** optionally show a local camera window during practice.

## Share a score at rehearsal

Open the score and choose **Share score**. On a compatible device, choose **Choose app or nearby device** to open its share sheet. On iOS, select AirDrop when available. Browsers without file sharing offer a download you can attach manually. An imported PDF is shared under its original filename. Personal annotations stay in the local library. Scores created from MusicXML share as MusicXML.

## Use the arranger’s notation with a PDF

When importing a PDF, choose **Matching MusicXML (optional)** if you have the same arrangement in MusicXML or MXL. Select **Import paired score** to read the original PDF and use the supplied notation for playback and editing. Studio trusts the files you pair, so check that both are the same edition. The combined upload limit is 40 MB. PDF-only imports continue through local recognition.

## Scanning and accuracy

Recognition is a draft: check parts, bar alignment, time signatures, notes, rhythms and lyrics against the original before relying on playback. Select music pages to skip covers. Clickable SATB choir, SATB + piano and Piano presets consolidate compatible part assignments; use Automatic for orchestral or changing layouts. Structural checks flag possible problems but cannot establish that every note is correct. Playback highlighting currently applies to the **digital notation**, not to matching locations on the original PDF.

New uploads and **Check score → Rescan with options…** use the same automatic preparation. Studio checks the spacing of repeated five-line staves on a sample of selected engraved PDF pages. For closely spaced staves, it raises the Audiveris render resolution up to 400 DPI, subject to the largest selected page and a tighter memory budget on the hosted service. Raster scans have a separate preparation step for faded ink, uneven lighting and skew. If an enhanced pass fails to transcribe or produces no notation, Studio can retry the original at standard settings. The imported file stays available for comparison. After a successful rescan of playable notation, **Undo** restores the previous version.

On PDFs with embedded Bravura or Leland music symbols, Studio can also recover a missing opening meter, including common and cut time, when the expected opening staves agree. Image-only scans rely on Audiveris for meter recognition.

The optional [`score-layout-preflight` skill](skills/score-layout-preflight/SKILL.md) helps an assistant map systems and parts, review proposed boundaries and export checked system crops. It supports arbitrary ensembles, including orchestral layouts. It is not connected to the Studio Scan button, and its effect on recognition accuracy has not yet been benchmarked. See the [recognition roadmap](docs/RECOGNITION_ROADMAP.md).

### Local choir benchmarks

Studio includes Java changes to Audiveris's notehead matcher and MusicXML exporter. The hosted image builds the patched engine, and the local app can use its own private copy. [Engine changes and build instructions](engine/README.md)

Run `python -m benchmarks.choir "path/to/score.pdf"` inside the Studio environment. The runner recognizes the two test editions by SHA-256, creates a separate temporary library, and reports part lengths, opening tempo, recognized tuplet groups and elapsed time. The five-page middle benchmark uses Automatic grouping. The fourteen-page advanced benchmark uses SATB + piano and checks the printed 55 bars and opening dotted quarter = 72 (quarter = 108). Counts describe the export. Pitch, lyrics and later tempo directions still require comparison with the PDF.

In **Reading options**, toggle **Follow the music** or **Hide silent staves**. Turn off the latter to see rests while editing. In **Check score → Check recognized tuplets**, select a group to locate its bar. **Use regular notes** removes a simple false tuplet and restores the written note lengths. Undo restores the group. The scan notification can be collapsed while recognition continues.

## Local data and limitations

Scores, original imports, annotations and history are stored under `data/`, which is excluded from Git. Back up that directory to preserve your library. The desktop launcher listens on the local computer. For a shared browser workspace use the hosted setup below. Some complex notation, repeat navigation and expressive playback require manual review. See the [Studio guide](docs/STUDIO.md) and [platform plan](docs/PLATFORM.md) for details.

## Tests and project structure

```powershell
.venv\Scripts\python.exe -m pytest tests -q
node tests/test_sampled_audio.cjs
```

- `src/studio/` — local server, library, notation, playback and interface
- `src/core/` — solfège and MusicXML logic
- `skills/score-layout-preflight/` — optional layout-assistance skill
- `tests/` — notation, timing, persistence and audio-loading checks
- `src/ui/` and `src/ocr/` — earlier Streamlit reader and OMR adapters

The earlier Streamlit prototype remains available separately; see [QUICKSTART.md](QUICKSTART.md). Bundled audio and PDF viewer components retain their license notices in `src/studio/static/`.

See [production-readiness criteria](docs/PRODUCTION_READINESS.md) for the MuseScore-inspired editing and reliability work still required before a production release.


## Correct a scanned bar

Open **Check score** to compare the original PDF with the recognized music. Warnings are grouped by bar. Expand **Bar timing by part** and select a bar to see how much of it each part fills. Chords and overlapping voices count once, rests count toward the total, and grace notes use no beats. A duration that fits 3/4 can also be a short bar in 4/4. Use the printed signature to decide.

- In **Check score** or **Compose**, drag a pitched note vertically to change its staff position. The preview shows the target pitch. A drag retains the accidental.
- To enter an exact pitch, click the note, choose **Change pitch on piano**, then play the on-screen piano or the indicated computer keys.
- For missing beats in a simple bar, select the preceding note, choose **Insert after on piano**, set the length, then play the missing pitches. Each new note becomes the anchor for the next. Undo restores the previous edit. Linked and multi-voice passages may require MusicXML editing.
- Scanning now expands contrast on faded raster pages. If an ensemble preset cannot match the detected staves, Studio keeps the automatic grouping and adds a review note. Library cards show when scores were added and updated. Duplicate library titles receive numbered suffixes before the file extension.

## Host a shared Studio on Render and Neon

1. In Neon create a Postgres project in Singapore. In **Connect**, copy the pooled connection string including its TLS parameters.
2. In Render choose **New → Blueprint** and select this repository on `main`. The blueprint creates one free Docker web service in Singapore. Paste the Neon connection string into the secret `DATABASE_URL` field.
3. Open the service URL over HTTPS. Use username `studio` and the generated `STUDIO_PASSWORD` from Render’s Environment page. This signs you into the owner library. In the account menu choose **Create invitation** and send the one-use link to one friend. They choose their own username and password. Each personal library has separate scores, originals, annotations and undo history. Invitations expire after seven days. Keep the owner password private.
4. Import a small PDF to check scanning on your instance. The container includes Audiveris and English, Simplified Chinese and Traditional Chinese OCR data. Large scans can exceed a free instance’s memory. Restarted instances lose active scans and temporary logs. Saved scores, originals and edit history reside in Neon. A newly hosted workspace starts with a demo score.

[Render Blueprint settings](https://render.com/docs/blueprint-spec) · [Neon connection setup](https://neon.com/docs/connect/connect-from-any-app)


## Read and edit on a tablet

**Read notation** opens the editable engraving. **Original PDF** opens the source pages. **Check score** opens both in comparison using the original page dimensions and available encoded page breaks. Missing recognition or missing page breaks can still put different bars opposite one another.

In **Check score** and **Compose**, drag a symbol from the top palette, or select it and tap the staff. Place a note within a rest to split that rest at the selected subdivision. Drop articulations directly onto notes. Drag a pitched note vertically for an immediate staff preview. Undo and redo support Ctrl/Cmd+Z, Ctrl+Y and Cmd/Ctrl+Shift+Z. **Reading options** remembers the title and toolbar spacing on this device. On small screens **Library** opens the navigation drawer.

The hosted project shares its database storage allowance across personal libraries. Original PDFs, MusicXML, duplicated scores, trash and edit history all use space. See [current Neon plan limits](https://neon.com/docs/introduction/plans).
