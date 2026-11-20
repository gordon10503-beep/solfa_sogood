# Audiveris 5.11.0 choir recognition ablation

The reference is the source MusicXML used to engrave each PDF, independent of the recognition output. Morning light has four SATB parts across eight bars. The two-part lyrical duet has four bars in 6/8. The compact page repeats Morning light at a smaller staff size. These are two distinct pieces, three page conditions and one engraving family. Both source scores and the exact PDF bytes are in [fixtures](../benchmarks/fixtures). Verovio 5.7 rendered the Leland notation. The printed outlines do not provide reliable embedded font evidence, so the experiment explicitly supplies the known font.

## Reproduce

With Studio dependencies and Audiveris 5.11.0 installed, run from the repository root. Each destination must be new. The runner retains the complete baseline and each experiment's export, log, settings and elapsed time.

~~~sh
python -m benchmarks.profile_trial benchmarks/fixtures/satb.pdf benchmarks/fixtures/satb.musicxml build/trial-satb --font Leland --quality Synthetic
python -m benchmarks.profile_trial benchmarks/fixtures/duet.pdf benchmarks/fixtures/duet.musicxml build/trial-duet --font Leland --quality Synthetic
python -m benchmarks.profile_trial benchmarks/fixtures/satb-compact.pdf benchmarks/fixtures/satb.musicxml build/trial-compact --font Leland --quality Synthetic
~~~

## Measurements

All 16 runs exported readable full-page MusicXML. Each cell gives exact pitched events shared with the reference. Every run had zero additional pitched events under the matching rule. The remaining reference events were missing. Four standard-page runs per piece and eight compact-page runs varied only the indicated settings within each page condition.

| Full page | Engine defaults | Leland only | Synthetic only | Leland + Synthetic |
|---|---:|---:|---:|---:|
| SATB, 300 DPI | 59/59 | 59/59 | 59/59 | 59/59 |
| Duet, 300 DPI | 23/23 | 23/23 | 23/23 | 23/23 |
| Compact SATB, 300 DPI | 47/59 | 58/59 | 47/59 | 58/59 |
| Compact SATB, Studio's existing 400 DPI choice | 47/59 | 59/59 | 47/59 | 59/59 |

- **Part grouping.** Every export had the correct part count and staff count per part. Both standard pages retained all part names. Every 300 DPI compact export read Alto as “Alm”. Every 400 DPI compact export read Tenor as “Ten or” and Bass as “Voice”.
- **Structure.** Every export had consistent part declarations and matching bar numbers across parts. The 47-event exports contained seven of eight bars and six short-bar findings. The 58-event exports contained eight bars and one short-bar finding. The remaining exports had the expected bar counts and zero inspection findings. These checks cover selected structural properties and do not constitute full MusicXML schema validation.
- **Event matching.** Compare multisets by part order, staff, bar order, rational onset, spelled pitch with octave, and rational duration. An omitted measure can disturb all subsequent positional matches. Voice labels, lyrics, ties, grace notes, tempo and expressive marks are outside this metric.
- **Artifacts.** The [machine-readable measurements](../benchmarks/results/results.json) include input hashes, actual part names, bar counts, structural findings and example differences. The [full-page export archive](../benchmarks/results) retains the baseline and every candidate.
- **Private score trial.** On page three of the advanced choir score, the baseline and optional Leland trial both exported five parts with six bars each. They shared 61 exact events, with 27 baseline-only and 53 trial-only. These are disagreements between transcriptions. Deciding which events are correct requires a verified reference. The parent MusicXML, PDF and revision stayed identical in this trial.

## Decision and next experiment

Keep normal scan settings unchanged. The known Leland setting helped the compact fixture. Synthetic quality added zero exact matches in this sample. The fixtures do not establish a speed improvement or generalize to photographed pages, dense SATB with piano, tuplets, multilingual lyrics or other engravers. Poor quality mode is available for an explicit trial and remains unbenchmarked here.

Use Check score → Compare a page scan to request one complete source page and inspect the separate result. The evidence preset abstains on ambiguous fonts or unknown image quality. If baseline page correspondence cannot be established, inspect the exports separately. No system crops are automatically merged. Before any future merge, verify clef, key, meter, part identity, measure order and ties crossing every boundary. The next benchmark should add independently proofread, held-out pages for these failure modes before considering automatic selection or model training.
