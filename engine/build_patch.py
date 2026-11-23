"""Build the Studio recognition and export patches in a private Audiveris 5.11.0 distribution."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path, help="Directory containing audiveris.jar and its dependency jars")
    parser.add_argument("--jdk-bin", type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve()
    jdk = args.jdk_bin.resolve()
    patches = [
        ("score/PartwiseBuilder.java", ["timed-wedges.patch", "held-lyric-ending.patch"], "490ce0a76e54be61778f887e6e5d5a00a478ab6e83454cf6cfdfba19ea8f6e61"),
        ("image/Template.java", ["notehead-mask.patch"], "a67df896f0327bf9cbe00a8ac9a60cface8617c6158f2196e81ce31d89883adb"),
        ("sheet/curve/EndingsBuilder.java", ["ending-staff-bars.patch"], "2f9a08caf8c334e0a61802f8563b3a681b8e19f1cc68196c92e0824939323aed"),
    ]
    with zipfile.ZipFile(app / "audiveris.jar") as jar:
        if b"Implementation-Version: 5.11.0" not in jar.read("META-INF/MANIFEST.MF").splitlines():
            parser.error("The engine patches require Audiveris 5.11.0.")
        header = jar.read("org/audiveris/omr/score/PartwiseBuilder.class")[:8]
    release = str(int.from_bytes(header[6:8], "big") - 44)
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        sources = []
        for name, patch_files, digest in patches:
            url = "https://raw.githubusercontent.com/Audiveris/audiveris/5.11.0/app/src/main/java/org/audiveris/omr/" + name
            source = work / Path(name).name
            data = urllib.request.urlopen(url, timeout=60).read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"Unexpected Audiveris source revision for {name}")
            # The pinned sources use CRLF. Git on Linux matches our LF patch
            # context literally. Verify upstream bytes first, then normalize.
            source.write_bytes(data.replace(b"\r\n", b"\n"))
            sources.append(str(source))
            for patch in patch_files:
                subprocess.run(["git", "apply", str(Path(__file__).with_name(patch).resolve())], cwd=work, check=True)
        classes = work / "classes"
        classes.mkdir()
        subprocess.run([str(jdk / "javac"), "--release", release, "-proc:none", "-encoding", "UTF-8",
                        "-classpath", str(app / "*"), "-d", str(classes), *sources], check=True)
        subprocess.run([str(jdk / "jar"), "uf", str(app / "audiveris.jar"), "-C", str(classes), "."], check=True)

        (app / "solfa-engine-v1").touch()


if __name__ == "__main__":
    main()
