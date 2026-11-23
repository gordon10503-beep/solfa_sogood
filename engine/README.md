# Studio's Audiveris engine

Studio applies four Java source patches to upstream Audiveris 5.11.0. The Render Docker build compiles them against the libraries in the pinned release. On Windows, Studio detects a successfully patched private installation under `build/studio-audiveris`. An explicit `AUDIVERIS_CMD` still takes priority.

* **MusicXML export.** Index hairpin endpoints by measure once per active system. If an endpoint has an unresolved chord time or an empty chord, omit that uncertain marking. Previously a null timestamp during sorting or traversal could abort an entire part-measure, including its notes.
* **Notehead matching.** Cache the template coordinates in three arrays for foreground, background and hole samples. For a template wholly inside the image with the stock integer weights, count valid and mismatched samples by category. This produces the same weighted distance, including the treatment of masked pixels. Clipped placements and custom weights take the original path.
* **Ending recognition.** When searching for a vertical stroke that divides a repeat bracket, only consider barlines on the bracket's own staff. The upstream lookup searches every staff in the system. [Audiveris EndingsBuilder](https://github.com/Audiveris/audiveris/blob/5.11.0/app/src/main/java/org/audiveris/omr/sheet/curve/EndingsBuilder.java)
* **Lyric extenders.** During export, check an unnumbered, legless bracket on a lower part against the lyrics on the previous system and the heads and ties on the staff above. Suppress the inferred ending only for a single sustained staff pitch with recognized ties at both ends and no competing repeat evidence in that system. A manual mark, linked text or number, vertical leg, or ending in the preceding system preserves the usual export. The saved OMR book retains the detected line. [Audiveris PartwiseBuilder](https://github.com/Audiveris/audiveris/blob/5.11.0/app/src/main/java/org/audiveris/omr/score/PartwiseBuilder.java)

To rebuild a local installation, copy Audiveris 5.11.0 into the private build directory and run the following from the repository root with Python, Git and a JDK that supports the installed engine's class version. The Windows benchmark used JDK 25.

```powershell
Copy-Item 'C:/Program Files/Audiveris' 'build/studio-audiveris' -Recurse
python engine/build_patch.py build/studio-audiveris/app --jdk-bin 'C:/path/to/jdk/bin'
```

Use a fresh destination for the copy. Subsequent rebuilds only require the Python command. The build checks the release manifest and SHA-256 of each upstream source file, applies the patches and updates the private engine jar. Run `python -m benchmarks.choir "path/to/score.pdf"` with each engine to compare Studio imports. For an isolated exporter comparison, copy the same saved OMR book into two separate directories and run each executable with `-batch -export -- path/to/copy.omr`.

The engine modifications are distributed under the GNU Affero General Public License v3. The matching upstream source and build files are available in the [Audiveris 5.11.0 source tree](https://github.com/Audiveris/audiveris/tree/5.11.0).

## Measured on the private choir benchmarks

On Windows, each engine transcribed page one through the PAGE step with the same PDF and options. The runs used opposite engine order for the two scores. Timings include JVM startup and saving the book. Each cell is one run.

| Benchmark | Stock | Patched | Recognized heads agreeing on position, shape, pitch, staff and grade |
| --- | ---: | ---: | ---: |
| Middle | 49.40 s | 46.36 s | 254 of 254 |
| Advanced | 26.70 s | 23.03 s | 85 of 85 |

To isolate export from recognition, both engines also exported identical copies of each full saved book. The advanced score went from 25 part-measure export exceptions to zero and from 934 to 1,055 exported pitched note elements. The five part lengths changed from 49/50/49/55/52 to 56/56/56/56/56. The print has 55 bars. Both middle exports contained 82 measures per part and 1,436 pitched elements. These counts measure dropped content and assembly. Individual recovered pitches and rhythms still need independent checking.

### Repeat endings and held lyrics

The following comparisons use the preceding Studio engine (notehead and wedge patches) as the baseline. Full-page inputs and the original four-page PDF were retained. The local test copy of Grow for Me has a line below the singer's held “me” on the final system. The PDF shows a lyric extender. The baseline book attached it to the upper piano staff, with neither vertical leg nor recognized number. The exporter then supplied a first-ending number.

| Test | Observed result |
|---|---|
| Same full Grow for Me book, two exporters | Removed the false first-ending start at bar position 57 and discontinue at 60. Both outputs had 61 bars per part, the same four vocal ending marks and 1,138 exact pitched events in common with zero additions or losses. |
| Fresh Studio import with the updated engine | 111 s on local Windows. Reproduced the removal and all 1,138 baseline events. All 12 manually verified opening vocal notes matched. |
| Fresh full-page scans of page 2 | Both found the same two bracket segments in system 2, none in system 1, and the same 334 exact pitched events. The staff lookup change showed no accuracy gain on this page. The opening segment at bar 14 still requires manual review. |
| Copies of the full book with controlled changes | Marking the line manual, linking an explicit “2.” ending-number sentence, or removing tie evidence each preserved the piano bracket in the export. |
| Saved advanced choir book and SATB fixture | Baseline and candidate matched on all 1,055 and 59 pitched events, respectively, and on all ending marks (nine and zero). These comparisons assess export stability. |

To repeat the whole-score check, run `python -m benchmarks.choir "grow for me.pdf"`. Inspect `endingMarksOverFinalLyricExtender` (expected empty) separately from `matchesFirstAndSecondEndingOnPageTwo` (still false). To run the exporter regression, point `SOLFA_GROW_OMR` at the four-page baseline book and run `python -m pytest -q tests/test_engine_endings.py` with the patched scanner. Counts use bar positions from the beginning, including the pickup.
