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

Keep normal scan settings unchanged. The known Leland setting helped the compact fixture. Synthetic quality added zero exact matches in this sample. The fixtures do not establish a speed improvement or generalize to photographed pages, dense SATB with piano, tuplets, multilingual lyrics or other engravers.

Use Check score → Compare a page scan to request one complete source page and inspect the separate result. The evidence preset abstains on ambiguous fonts or unknown image quality. If baseline page correspondence cannot be established, inspect the exports separately. No system crops are automatically merged. Before any future merge, verify clef, key, meter, part identity, measure order and ties crossing every boundary. The next benchmark should add independently proofread, held-out pages for these failure modes before considering automatic selection or model training.

## Private rehearsal scores

The private benchmark runner checks the PDF hash before scanning. The small vocal references in `benchmarks/choir.py` were read from the printed page. They cover the first staff only and count the two written segments of a tie separately. The PDF, handwriting, lyrics and full private transcriptions stay outside the repository.

~~~sh
python -m benchmarks.choir "grow for me.pdf"
python -m benchmarks.choir "grow for me.pdf" --opening-profile Poor
python -m benchmarks.choir "道別是一件難事_SATB_pinyin.pdf" --opening-profile Leland
~~~

| Grow for Me | Runtime on local Windows | Bars per part | Verified vocal events in bars 1–4 | Structural findings |
|---|---:|---:|---:|---|
| Complete PDF, engine baseline | 118.3 s | 61 | 12/12, zero extra | 12 short, 2 overfull |
| Full first page, Standard quality | 28.79 s | 12 | 12/12, zero extra | 3 short, 1 overfull |
| Full first page, Poor quality | 28.99 s | 12 | 12/12, zero extra | 3 short, 1 overfull |

All three runs exported a vocal staff and piano grand staff. The first-page runs shared 215 exact events across the voice and piano. Poor produced two more events outside the verified excerpt. Their correctness is unknown. This trial supplies no reason to enable Poor automatically. The full export expands to 76 playback bars when repeats are followed.

On the middle benchmark, both previously archived exports matched the three sung quarter notes of Part I in bar 3. A separate saved library copy matched one. Its unclosed 15ma instruction and final A♯6 conflict with the printed A♯4. Testing the proposed repair in memory brought that bar to two matches. Its opening C♯4 still needs a manual correction. The review action requires evidence from another staff and the following note. Neither archived middle export nor either advanced export triggered it. This measures a specific repair on a saved copy and does not estimate overall recognition accuracy.

Two fresh scans of the middle score's complete first page both recovered I, II and the piano grand staff, 15 bars in each part, and all three verified vocal events. Standard produced 253 events and four short-bar findings in 94.00 seconds. The Leland trial produced 234 events and seven short-bar findings in 53.72 seconds. The exports shared 233 events, with 20 unique to Standard and one unique to Leland. There was one timed run per setting on a machine also running other workloads. Neither the timing difference nor the unverified disagreements establish a winning profile.

**Repeat check.** Page 2 of Grow for Me starts the first ending at “please” (bar position 14), spans a system break, and ends at 17. Audiveris placed the whole first ending in 17. On an in-memory copy of the full export, extending that ending in Studio preserved the 17 → 2 repeat and changed the second pass from 16 → 18 to the printed 13 → 18. Playback then contained 73 bar positions. The review control requires a user to supply the printed start and rejects changes that would cross another repeat or ending.

**Reader and playback timings.** The local Chrome comparison used commit `01aa477` as the baseline, a fresh server and browser context per case, and alternating version order. The reader fixture used the 679,445-byte middle-score MusicXML with a 1,367,136-byte original PDF. The notation case used the same MusicXML by itself.

| User action | Baseline median | Updated median | Measurement |
|---|---:|---:|---|
| Open original PDF | 2,273 ms | 724 ms | Five opens per version, click to first sheet canvas mounted and next animation frame |
| Open notation alone | 1,372 ms | 1,422 ms | Five opens per version, click to first selectable note mounted and next animation frame |
| Start playback | 1,531 ms | 185 ms | Three cold starts per version, 80 ms artificial delay per sample request, click to transport entering playback |

In a separate horizontal navigation check, returning from page two to page one recreated the first canvas in 764 ms on the baseline. The updated reader reused the same canvas in 12 ms. This was one observed back turn per version.

The opening sheet uses a bounded PNG raster of the original PDF. PDF.js supplies the fallback and subsequent pages. Playback started after two sample responses in the measured score, down from 37. Until an exact sample finishes decoding, Studio transposes the closest loaded sample from the selected instrument. The notation measurement showed no startup gain. Device audio-output latency, iPad frame rate and hosted database/network latency were outside these tests.
