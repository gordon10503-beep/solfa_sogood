const {test} = require("node:test");
const assert = require("node:assert/strict");
const {spawn} = require("node:child_process");
const {once} = require("node:events");
const {createInterface} = require("node:readline");
const {mkdtemp, rm} = require("node:fs/promises");
const {tmpdir} = require("node:os");
const path = require("node:path");

let chromium;
try { ({chromium} = require("playwright-core")); } catch (error) {
  if (error.code !== "MODULE_NOT_FOUND") throw error;
}

const fixture = `
import sys
import pymupdf
from pathlib import Path
from src.studio.document import new_score, replace_bar
from src.studio.server import Library, StudioServer
lib = Library(Path(sys.argv[1]) / "review.sqlite3")
xml = replace_bar(new_score(template="melody", bars=2), 0, 0, "C4/q R/q E4/h")
with pymupdf.open() as pdf:
    pdf.new_page(width=400, height=560).insert_text((30, 60), "Original vocal score")
    lib.add(xml, {"origin": "Scan", "title": "Review fixture"}, pdf.tobytes(), "application/pdf")
server = StudioServer(("127.0.0.1", 0), lib)
print(server.server_address[1], flush=True)
server.serve_forever()
`;

async function enterReview(page) {
  await page.locator("#library-cards").getByText("Review fixture").click();
  await page.locator("#scan-banner").click();
  await page.locator("#pages .note").first().waitFor();
  assert.equal(await page.locator("body").getAttribute("data-page"), "review");
}

async function moveTouch(session, gesture, x, y) {
  const touchPoints = gesture === "touchEnd" ? [] : [{x, y, id: 1, radiusX: 1, radiusY: 1}];
  await session.send("Input.dispatchTouchEvent", {type: gesture, touchPoints});
}

test("Check score touch drags for pitch and note/rest length persist and undo", {
  skip: !chromium && "requires playwright-core and Chrome", timeout: 90000,
}, async t => {
  const dir = await mkdtemp(path.join(tmpdir(), "studio-touch-review-"));
  const server = spawn(process.env.STUDIO_PYTHON || "python", ["-u", "-c", fixture, dir],
    {windowsHide: true, stdio: ["ignore", "pipe", "inherit"]});
  const stdout = createInterface({input: server.stdout});
  t.after(async () => {
    stdout.close();
    if (server.exitCode === null && server.signalCode === null) {
      const exited = once(server,"exit");
      server.kill();
      await exited;
    }
    await rm(dir,{recursive:true, force:true});
  });
  const port = await Promise.race([
    once(stdout,"line").then(([line]) => Number(line)),
    once(server,"exit").then(() => { throw Error("Review fixture server stopped"); }),
  ]);
  const browser = await chromium.launch({channel:"chrome"});
  t.after(() => browser.close());

  for (const [width,height] of [[820,1180],[375,812]]) {
    await t.test(width+"px touchscreen", async () => {
      const page = await browser.newPage({viewport:{width,height},hasTouch:true,isMobile:true});
      try {
        await page.goto("http://127.0.0.1:"+port);
        await enterReview(page);
        const first = page.locator('#pages .note[role="button"]').first();
        await first.scrollIntoViewIfNeeded();
        const id = await first.getAttribute("id");
        const initial = await first.getAttribute("aria-label");
        assert.match(initial,/C4$/);
        const touch = await page.context().newCDPSession(page);
        async function dragPreview(element, dx, dy) {
          await element.scrollIntoViewIfNeeded();
          const pt = await element.evaluate(el => {
            const r = el.querySelector(":scope > rect").getBoundingClientRect();
            return {x:r.left+r.width/2, y:r.top+r.height/2};
          });
          await moveTouch(touch,"touchStart",pt.x,pt.y);
          await moveTouch(touch,"touchMove",pt.x+dx,pt.y+dy);
          await page.locator("#drag-pitch").waitFor({timeout:3000});
          return (await page.locator("#drag-pitch").textContent()).trim();
        }
        async function releaseEdit() {
          const edit = page.waitForResponse(r => r.url().endsWith("/api/edit"), {timeout:5000});
          await moveTouch(touch,"touchEnd");
          assert((await edit).ok());
        }
        const target = await dragPreview(first,0,-12);
        assert.notEqual(target,"C4");
        await releaseEdit();
        await page.waitForFunction(({id,target}) => document.getElementById(id)?.getAttribute("aria-label")?.endsWith(target), {id,target});
        assert.equal(await page.locator("body").getAttribute("data-page"),"review");
        await page.reload();
        await enterReview(page);
        assert((await first.getAttribute("aria-label")).endsWith(target));
        await page.locator("#history-back").click();
        await page.waitForFunction(({id,initial}) => document.getElementById(id)?.getAttribute("aria-label")===initial, {id,initial});
        assert.equal(await page.locator("body").getAttribute("data-page"),"review");

        const {scores} = await (await page.request.get(new URL("/api/library",page.url()).href)).json();
        const scoreId = scores.find(s => s.title === "Review fixture").id;
        const exportedNotes = () => page.evaluate(async scoreId => {
          const source = await (await fetch("/api/xml/"+scoreId)).text();
          const doc = new DOMParser().parseFromString(source,"application/xml");
          const bar = doc.querySelector("part > measure");
          const div = Number(bar.querySelector("divisions").textContent);
          return Array.from(bar.querySelectorAll("note"), n => ({
            step: n.querySelector("pitch > step")?.textContent ?? "rest",
            duration: Number(n.querySelector("duration").textContent)/div,
          }));
        },scoreId);
        for (const [at,selector] of [[0,".note"],[1,".rest"]]) {
          const before = await exportedNotes();
          const glyph = page.locator("#pages "+selector+'[role="button"]').first();
          const hint = await dragPreview(glyph,-49,0);
          assert(hint.length, "Expected a snapped length during the gesture");
          await releaseEdit();
          await page.waitForFunction(() => document.querySelector("#busy").hidden);
          const changed = await exportedNotes();
          assert.equal(changed[at].step,before[at].step);
          assert(changed[at].duration>0 && changed[at].duration<before[at].duration);
          assert.equal(await page.locator("body").getAttribute("data-page"),"review");
          await page.reload();
          await enterReview(page);
          assert.deepEqual(await exportedNotes(), changed);
          const undone = page.waitForResponse(r=>r.url().endsWith("/api/undo"));
          await page.locator("#history-back").click();
          assert((await undone).ok());
          await page.waitForFunction(() => document.querySelector("#busy").hidden);
          assert.deepEqual(await exportedNotes(), before);
          assert.equal(await page.locator("body").getAttribute("data-page"),"review");
        }
      } finally { await page.close(); }
    });
  }
});
