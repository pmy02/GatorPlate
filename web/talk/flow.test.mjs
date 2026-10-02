// Typing mode completes Maria (English) and Sofia (Spanish) in fixture mode: the talk page's call sequencing and
// state machine run against the fixture reply lists, and every request body and fixture reply is checked against
// contracts/brain_api.v1.schema.json (docs/BRAIN_API.md §5, §6, §10). Run with `make test-web WEB=web/talk`.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { TalkSession, canSend, cardHref, displayText, initialState, reduce, speechPlan } from "./core.js";
import { STRINGS } from "./strings.js";

// The browser and speech-service sentences of the web disclosure, as the page's privacy line has them.
const disclosure = (lang) => STRINGS[lang].privacy.split(lang === "es" ? " Guardamos" : " We keep")[0];

const read = (rel) => JSON.parse(readFileSync(new URL(rel, import.meta.url), "utf8"));
const schema = read("../../contracts/brain_api.v1.schema.json");
const index = read("../fixtures/index.json").routes;

// A small JSON Schema reader for the keywords the Brain API schema uses.
function check(value, node, path = "$") {
  if (node.$ref) return check(value, schema.$defs[node.$ref.split("/").pop()], path);
  const errors = [];
  const type = (v) => (v === null ? "null" : Array.isArray(v) ? "array" : Number.isInteger(v) ? "integer" : typeof v);
  if (node.type) {
    const types = [].concat(node.type);
    const t = type(value);
    if (!types.includes(t) && !(t === "integer" && types.includes("number"))) errors.push(`${path}: type ${t}`);
  }
  if ("const" in node && value !== node.const) errors.push(`${path}: const ${JSON.stringify(node.const)}`);
  if (node.enum && !node.enum.includes(value)) errors.push(`${path}: enum`);
  if (typeof value === "number") {
    if (node.minimum !== undefined && value < node.minimum) errors.push(`${path}: minimum`);
    if (node.maximum !== undefined && value > node.maximum) errors.push(`${path}: maximum`);
  }
  if (typeof value === "string") {
    if (node.maxLength !== undefined && value.length > node.maxLength) errors.push(`${path}: maxLength`);
    if (node.minLength !== undefined && value.length < node.minLength) errors.push(`${path}: minLength`);
    if (node.pattern && !new RegExp(node.pattern, "u").test(value)) errors.push(`${path}: pattern`);
  }
  if (Array.isArray(value)) {
    if (node.minItems !== undefined && value.length < node.minItems) errors.push(`${path}: minItems`);
    if (node.maxItems !== undefined && value.length > node.maxItems) errors.push(`${path}: maxItems`);
    if (node.items) value.forEach((v, i) => errors.push(...check(v, node.items, `${path}[${i}]`)));
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const key of node.required || []) if (!(key in value)) errors.push(`${path}: missing ${key}`);
    for (const [key, sub] of Object.entries(node.properties || {})) {
      if (key in value) errors.push(...check(value[key], sub, `${path}.${key}`));
    }
    if (node.additionalProperties === false) {
      for (const key of Object.keys(value)) if (!(key in (node.properties || {}))) errors.push(`${path}: extra ${key}`);
    }
  }
  for (const sub of node.allOf || []) errors.push(...check(value, sub, path));
  if (node.anyOf && !node.anyOf.some((sub) => check(value, sub, path).length === 0)) errors.push(`${path}: anyOf`);
  if (node.if) {
    const branch = check(value, node.if, path).length === 0 ? node.then : node.else;
    if (branch) errors.push(...check(value, branch, path));
  }
  return errors;
}

const valid = (value, def) => assert.deepEqual(check(value, schema.$defs[def]), [], `${def}: ${JSON.stringify(value)}`);

// The fixture API of shared/api.js: a reply list is served one element per request, start and turn share it.
function fixtureApi(lang) {
  const replies = read(`../fixtures/${index["POST /v1/calls/{call_id}/turn"][lang]}`);
  const sessionAnswer = read(`../fixtures/${index["POST /api/web/sessions"][lang]}`);
  const calls = [];
  let n = 0;
  const request = async (method, path, opts = {}) => {
    calls.push({ method, path, body: opts.body, token: opts.token });
    if (path === "/api/web/sessions") return structuredClone(sessionAnswer);
    if (path.endsWith("/end")) return {};
    const r = replies[Math.min(n, replies.length - 1)];
    n += 1;
    return structuredClone(r);
  };
  return { request, calls, replies };
}

// Play a whole call in typing mode: tap a quick reply when there is one, else type the student's line.
async function typingCall(lang, lines) {
  const { request, calls, replies } = fixtureApi(lang);
  const session = new TalkSession({ request, now: (() => { let t = 0; return () => (t += 7000); })() });
  let state = reduce(initialState({ lang }), { type: "start", mode: "typing", readAloud: false });
  const phases = [state.phase];
  await session.open(lang);
  let reply = await session.start();
  const shown = [];
  let li = 0;
  for (;;) {
    valid(reply, "BrainReply");
    shown.push(displayText(reply));
    state = reduce(state, { type: "reply", reply, speak: false });
    phases.push(state.phase);
    if (reply.end) {
      await session.end(reply.end_reason);
      break;
    }
    assert.ok(canSend(state), `can answer after: ${reply.display}`);
    const line = lines[li];
    li += 1;
    assert.ok(line, `a student line for: ${reply.display}`);
    const text = line === "choice:0" ? reply.choices[0] : line;
    state = reduce(state, { type: "send" });
    phases.push(state.phase);
    reply = await session.turn(text, { typed: true, lang });
  }
  return { state, session, calls, phases, shown, replies, used: li };
}

test("Maria (English, typing, fixtures): consent to card, every request valid", async () => {
  const lines = ["choice:0", "I'm an SF State undergrad, a junior, and I'm taking 12 units.",
    "I'm 20, and I live with two roommates.", "Separately",
    "I work at the campus library, about 900 a month. Nobody gives me cash.", "Eleven hundred.", "No",
    "About a thousand.", "No, thanks"];
  const { state, session, calls, phases, shown, replies, used } = await typingCall("en", lines);
  assert.equal(used, lines.length);
  assert.equal(replies.length, lines.length + 1);
  assert.equal(state.phase, "done");
  assert.equal(state.cardUrl, "/c/fixtureMariaCard000001");
  assert.equal(cardHref(state.cardUrl), "/c/fixtureMariaCard000001");
  assert.equal(cardHref(state.cardUrl, { fixtures: true, lang: "en" }), "/card/?fixtures=1&token=fixture&lang=en");
  assert.ok(phases.includes("thinking"));
  assert.equal(phases[0], "connecting");
  // The first thing on screen is the bank's web disclosure, which names the browsers' speech services.
  assert.match(shown[0], /^Hi, I'm GatorPlate, a student-built AI assistant, not an official SF State service\./);
  assert.ok(shown[0].includes(disclosure("en")), shown[0]);
  assert.match(shown.join(" "), /about \$306 a month\. The county makes the final decision\./);

  const [sess, start, ...rest] = calls;
  assert.deepEqual(sess.body, { lang: "en" });
  valid(sess.body, "WebSessionRequest");
  valid(start.body, "StartRequest");
  assert.equal(start.body.channel, "web");
  const turns = rest.filter((c) => c.path.endsWith("/turn"));
  assert.equal(turns.length, lines.length);
  turns.forEach((c, i) => {
    valid(c.body, "TurnRequest");
    assert.equal(c.body.seq, i + 1);
    assert.equal(c.body.typed, true);
    assert.equal(c.body.event, "utterance");
    assert.equal(c.body.masked, false);
    assert.equal(c.token, "fixture-web-token-maria-000001");
    assert.match(c.path, /^\/v1\/calls\/[a-f0-9]{32}\/turn$/);
  });
  assert.equal(turns[0].body.text, "Yes");
  const ends = calls.filter((c) => c.path.endsWith("/end"));
  assert.equal(ends.length, 1);
  valid(ends[0].body, "EndRequest");
  assert.equal(ends[0].body.reason, "completed");
  assert.equal(ends[0].body.turns, lines.length);
  assert.equal(session.active, false);
  assert.equal(session.beacon(), null);
});

test("Sofia (Spanish, typing, fixtures): the coordinator route ends with the card button", async () => {
  const lines = ["choice:0", "Estudio una licenciatura en SF State y tomo 12 unidades.",
    "Tengo 19 años y vivo con mis papás.", "No, gracias"];
  const { state, calls, shown, used } = await typingCall("es", lines);
  assert.equal(used, lines.length);
  assert.equal(state.phase, "done");
  assert.equal(state.lang, "es");
  assert.equal(state.cardUrl, "/c/example-card-token-sofia-0001");
  assert.ok(shown[0].includes(disclosure("es")), shown[0]);
  for (const c of calls.filter((x) => x.path.endsWith("/turn") || x.path.endsWith("/start"))) {
    assert.equal(c.body.lang, "es");
  }
  assert.deepEqual(calls[0].body, { lang: "es" });
  const end = calls.find((c) => c.path.endsWith("/end"));
  assert.equal(end.body.reason, "completed");
});

test("fixture replies: the opening is never interruptible, and amounts are spoken in full", () => {
  for (const lang of ["en", "es"]) {
    const replies = read(`../fixtures/${index["POST /v1/calls/{call_id}/start"][lang]}`);
    const opening = replies[0];
    assert.equal(opening.interruptible, false);
    const plan = speechPlan(opening);
    assert.ok(plan.length >= 3);
    assert.ok(plan.filter((c) => !c.interruptible).length >= 2, "the disclosure sentences can't be cut off");
    assert.equal(plan[plan.length - 1].interruptible, true, "the consent question can");
    for (const r of replies) valid(r, "BrainReply");
  }
});
