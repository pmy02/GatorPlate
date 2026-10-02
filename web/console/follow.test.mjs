// The live transcript sticks to the bottom unless the reader scrolled up (docs/UI_SPEC.md A3.8), also after a layout
// change in the middle of a call (node --test; run through `make test-web WEB=web/console`).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { followBottom, STICK_PX } from "./views/follow.js";

const here = path.dirname(fileURLToPath(import.meta.url));

// A stand-in for the transcript box: content height changes without a scroll event (layout), scrollTop is clamped,
// and scroll events are dispatched later, as a browser does (flush()).
class Box {
  constructor(clientHeight) {
    this.clientHeight = clientHeight;
    this.content = 0;
    this.top = 0;
    this.listeners = [];
    this.queued = false;
  }
  get scrollHeight() { return Math.max(this.content, this.clientHeight); }
  get scrollTop() { return this.top; }
  set scrollTop(v) {
    const next = Math.max(0, Math.min(v, this.scrollHeight - this.clientHeight));
    if (next !== this.top) { this.top = next; this.queued = true; }
  }
  addEventListener(type, fn) { if (type === "scroll") this.listeners.push(fn); }
  flush() { if (!this.queued) return; this.queued = false; for (const fn of this.listeners) fn(); }
  gap() { return this.scrollHeight - this.scrollTop - this.clientHeight; }
  // The reader scrolls: the position moves, then the event arrives.
  scrollBy(dy) { this.scrollTop = this.top + dy; this.flush(); }
  // A line arrives (live.js syncLines appends it, then pins).
  addLine(px, follow) { this.content += px; follow.pin(); this.flush(); }
  // Presenter on (16 → 18 px root) or a resize: everything grows; no scroll event, scrollTop stays.
  relayout(factor) { this.content = Math.round(this.content * factor); }
}

test("a Presenter toggle mid-call does not stop the transcript from following (the V4 repro geometry)", () => {
  const box = new Box(506);
  const follow = followBottom(box);
  for (let i = 0; i < 3; i += 1) box.addLine(140, follow); // turn 2: 420 px, no overflow yet
  assert.equal(box.scrollTop, 0);
  box.relayout(1.6); // Presenter on: 672 px of content in a 506 px box, still at scrollTop 0
  assert.ok(box.gap() >= STICK_PX, "the layout change alone leaves the newest line under the fold");
  follow.pin(); // the live view's render that the Presenter toggle runs
  box.flush();
  assert.equal(box.gap(), 0, "the render re-pins at once");
  for (let i = 0; i < 9; i += 1) box.addLine(160, follow); // turns 3 to 6
  assert.equal(box.gap(), 0, "the newest question and answer stay in view");
  assert.equal(box.scrollTop, box.scrollHeight - box.clientHeight);
});

test("a layout change with no render in between: the next line still pins to the bottom", () => {
  const box = new Box(506);
  const follow = followBottom(box);
  for (let i = 0; i < 6; i += 1) box.addLine(120, follow);
  assert.equal(box.gap(), 0);
  box.relayout(1.25); // grows by 180 px; no scroll event, so the reader's intent is unchanged
  assert.ok(box.gap() >= STICK_PX);
  assert.equal(follow.sticking(), true);
  box.addLine(150, follow);
  assert.equal(box.gap(), 0, "geometry measured when the line arrives would have said 'not at the bottom'");
});

test("the reader scrolled up: new lines leave the position alone until they scroll back down", () => {
  const box = new Box(500);
  const follow = followBottom(box);
  for (let i = 0; i < 10; i += 1) box.addLine(100, follow);
  assert.equal(box.gap(), 0);
  box.scrollBy(-300);
  assert.equal(follow.sticking(), false);
  const top = box.scrollTop;
  box.addLine(100, follow);
  follow.pin();
  assert.equal(box.scrollTop, top, "reading an older line is not interrupted");
  box.scrollBy(10_000); // back to the bottom
  assert.equal(follow.sticking(), true);
  box.addLine(100, follow);
  assert.equal(box.gap(), 0);
  box.scrollBy(-(STICK_PX - 1)); // a nudge within the slack still counts as the bottom
  assert.equal(follow.sticking(), true);
});

test("a resize of the box re-pins without waiting for a line; stop() lets the observer go", () => {
  const seen = [];
  class FakeRO {
    constructor(cb) { this.cb = cb; this.on = false; seen.push(this); }
    observe() { this.on = true; }
    disconnect() { this.on = false; }
  }
  const saved = globalThis.ResizeObserver;
  globalThis.ResizeObserver = FakeRO;
  try {
    const box = new Box(506);
    const follow = followBottom(box);
    for (let i = 0; i < 6; i += 1) box.addLine(120, follow);
    box.clientHeight = 400; // the window got shorter
    assert.ok(box.gap() >= STICK_PX);
    seen[0].cb([]);
    assert.equal(box.gap(), 0);
    follow.stop();
    assert.equal(seen[0].on, false);
  } finally {
    if (saved === undefined) delete globalThis.ResizeObserver; else globalThis.ResizeObserver = saved;
  }
});

test("the Live view follows through views/follow.js: on every new line and on every render", () => {
  const live = readFileSync(path.join(here, "views", "live.js"), "utf8");
  assert.match(live, /import \{ followBottom \} from "\.\/follow\.js";/);
  assert.match(live, /followBottom\(transcript\)/);
  const sync = live.slice(live.indexOf("function syncLines"), live.indexOf("function queueHeard"));
  assert.doesNotMatch(sync, /scrollHeight\s*-\s*\w+\.scrollTop/, "no geometry test when the lines arrive");
  assert.match(sync, /ui\.follow\.pin\(\)/);
  const render = live.slice(live.indexOf("function updateCase"), live.indexOf("function updateRange"));
  assert.match(render, /ui\.follow\.pin\(\);\s*\}\s*$/, "the last step of a live render re-pins");
  assert.match(live, /ui\.follow\.stop\(\)/, "a rebuilt view lets the old observer go");
});
