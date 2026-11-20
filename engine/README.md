# Studio's Audiveris engine

Studio applies two Java source patches to upstream Audiveris 5.11.0. The Render Docker build compiles them against the libraries in the pinned release. On Windows, Studio detects a successfully patched private installation under `build/studio-audiveris`. An explicit `AUDIVERIS_CMD` still takes priority.

* **MusicXML export.** Index hairpin endpoints by measure once per active system. If an endpoint has an unresolved chord time or an empty chord, omit that uncertain marking. Previously a null timestamp during sorting or traversal could abort an entire part-measure, including its notes.
* **Notehead matching.** Cache the template coordinates in three arrays for foreground, background and hole samples. For a template wholly inside the image with the stock integer weights, count valid and mismatched samples by category. This produces the same weighted distance, including the treatment of masked pixels. Clipped placements and custom weights take the original path.

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
