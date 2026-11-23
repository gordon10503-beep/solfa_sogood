const { test } = require("node:test");
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { mkdtemp, rm } = require("node:fs/promises");
const { tmpdir } = require("node:os");
const path = require("node:path");
const { once } = require("node:events");
const { createInterface } = require("node:readline");

let chromium;
try { ({ chromium } = require("playwright-core")); } catch (error) {
  if (error.code !== "MODULE_NOT_FOUND") throw error;
}

// Run against an isolated score so keyboard editing can never modify a user's library.
const fixture = `
import sys
import pymupdf
from pathlib import Path
from src.studio.document import new_score, replace_bar, read_xml, xml_bytes
from src.studio.server import Library, StudioServer
lib = Library(Path(sys.argv[1]) / "test.sqlite3")
xml = read_xml(replace_bar(new_score(template="melody", bars=3), 0, 0, "C4/q D4/q E4/h"))
attributes = xml.find("part/measure/attributes")
attributes.remove(attributes.find("time"))
with pymupdf.open() as pdf:
    for heading in ["Opening", "Second page"]:
        pdf.new_page().insert_text((50, 60), heading)
    lib.add(xml_bytes(xml), {"origin": "Scan", "title": "Rehearsal fixture"}, pdf.tobytes(), "application/pdf")
server = StudioServer(("127.0.0.1", 0), lib)
print(server.server_address[1], flush=True)
server.serve_forever()
`;

test("PDF rehearsal, issue navigation and keyboard note selection", {
  skip: !chromium && "requires playwright-core and Chrome",
  timeout: 60000,
}, async t => {
  const dir = await mkdtemp(path.join(tmpdir(), "studio-reader-test-"));
  const server = spawn(process.env.STUDIO_PYTHON || "python", ["-u", "-c", fixture, dir],
    { windowsHide: true, stdio: ["ignore", "pipe", "inherit"] });
  const lines = createInterface({ input: server.stdout });
  t.after(async () => {
    lines.close();
    if (server.exitCode === null && server.signalCode === null) {
      const exited = once(server, "exit");
      server.kill();
      await exited;
    }
    await rm(dir, { recursive: true, force: true });
  });
  const port = await Promise.race([
    once(lines, "line").then(([line]) => Number(line)),
    once(server, "exit").then(() => { throw Error("Fixture server stopped"); }),
  ]);
  const browser = await chromium.launch({ channel: "chrome" });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 375, height: 812 }, hasTouch: true });
  await page.goto("http://127.0.0.1:" + port);
  await page.locator("#library-cards").getByText("Rehearsal fixture").click();
  await page.locator("#pdf-pages canvas").first().waitFor();
  assert((await page.locator("#pdf-pages").boundingBox()).y < 220);
  const pen = page.locator('[data-ink="pen"]');
  await pen.focus();
  await page.keyboard.press("Space");
  assert.equal(await pen.getAttribute("aria-pressed"), "true");
  assert.equal(await page.locator("#play").getAttribute("aria-label"), "Play score");
  await page.locator("#spread-tools").click();
  await page.locator("#pdf-layout").selectOption("2");
  await page.locator(".pdf-spread").first().locator("canvas").nth(1).waitFor();
  await page.locator("#scan-banner").click();
  await page.locator("#issue-detail").waitFor();
  await page.locator("#issue-correct").click();
  assert(await page.locator("#meter-beats").isVisible());
  const current = page.locator('#pages [tabindex="0"]');
  assert.equal(await current.count(), 1);
  const first = await current.getAttribute("id");
  await current.focus();
  await page.keyboard.press("ArrowRight");
  assert.notEqual(await current.getAttribute("id"), first);
  await page.keyboard.press("Alt+i");
  assert(await page.locator("#issue-open").evaluate(el => el === document.activeElement));
});
