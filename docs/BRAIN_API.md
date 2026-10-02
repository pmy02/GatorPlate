# GatorPlate Brain API v1

**Status: frozen on 2026-10-01.** This page explains the contract in words. The machine-readable contract is
[`contracts/brain_api.v1.schema.json`](../contracts/brain_api.v1.schema.json) (JSON Schema 2020-12), the shared test
vectors are in [`contracts/examples/`](../contracts/examples/), and `python3 contracts/check_examples.py` checks
both. If this page and the schema ever disagree, the schema wins.

---

## 1. Purpose

GatorPlate's brain runs the CalFresh check conversation. Two clients use the same API:

| Client | Channel | Languages | Auth |
|---|---|---|---|
| A hosted voice gateway (phone calls) | `phone` | English (plus one Spanish notice, see [BrainReply](#6-brainreply)) | signed requests |
| The GatorPlate talk page in the browser | `web` | English and Spanish | bearer token |

- **The client handles audio and timing; GatorPlate decides every word.** Requests carry text, events and counters
  only. They never carry audio, and never the student's phone number or anything derived from it.
- **The model listens, rules decide, templates speak.** The language model only extracts answers. Every sentence in
  a reply comes from GatorPlate's sentence bank, and code inserts every number. The conversation policy (which
  question comes next, when a result is given) is described in `docs/SPEC.md`.
- **One call, one `call_id`:** `/start` once, `/turn` once per event, `/end` once.

---

## 2. Endpoints

| Method and path | Auth | Request body | 200 response body |
|---|---|---|---|
| `GET /v1/health` | none | none | `{"ok": true}` |
| `GET /v1/lines?lang=en` | gateway | none | [GatewayLines](#8-gatewaylines) |
| `POST /v1/calls/{call_id}/start` | gateway (phone) or bearer (web) | [StartRequest](#51-startrequest) | [BrainReply](#6-brainreply) |
| `POST /v1/calls/{call_id}/turn` | gateway (phone) or bearer (web) | [TurnRequest](#52-turnrequest) | [BrainReply](#6-brainreply) |
| `POST /v1/calls/{call_id}/end` | gateway (phone) or bearer (web) | [EndRequest](#53-endrequest) | `{}` |
| `POST /api/web/sessions` | none, 20 per hour per IP address | `{"lang": "en" \| "es"}` (may be `{}`) | `{"call_id", "token", "expires_at"}` |

- **`call_id`** is 32 lowercase hex characters (`^[a-f0-9]{32}$`). On the phone the gateway creates a new random
  UUID (version 4) for every call and writes it without dashes; on the web `/api/web/sessions` issues it.
- Bodies are UTF-8 JSON (`Content-Type: application/json`). Success is always **HTTP 200**; every other status
  carries an [error envelope](#12-errors).
- **Tolerant requests, closed replies.** The brain ignores unknown request properties. `BrainReply` and
  `GatewayLines` always contain exactly the properties listed here, no more and no fewer.
- `/v1/lines`, `/start`, `/end` and `/v1/health` never call the language model.

---

## 3. Authentication

### 3.1 Gateway (phone): signed requests

Every gateway request carries two headers:

```
X-GP-Timestamp: <unix seconds>
X-GP-Signature: v1=<hex HMAC-SHA256(secret, "{ts}.{METHOD}.{path}.{sha256_hex(body)}")>
```

| Part | Exact meaning |
|---|---|
| `ts` | The `X-GP-Timestamp` value exactly as sent: whole seconds, digits only. |
| `METHOD` | HTTP method in upper case: `GET` or `POST`. |
| `path` | URL path exactly as sent, without scheme, host or query string. `GET /v1/lines?lang=en` signs `/v1/lines`. |
| `sha256_hex(body)` | Lowercase hex SHA-256 of the exact body bytes sent. The empty body (GET) gives `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. |
| key | The UTF-8 bytes of the shared secret string as stored. Do not base64-decode it. |
| signature | Lowercase hex, prefixed with `v1=`. |

The secret is the setting `GP_GATEWAY_SECRET` (48 random bytes as URL-safe base64 text); the gateway holds the same
value. It is generated **once, on the gateway side**, and set in GatorPlate's deployment settings with a command that
never prints it; GatorPlate's own build never generates it. A different value on the two sides makes every phone call
fail at `/start` with **401 `bad_signature`**.

Signing in Python:

```python
import hashlib, hmac, time

def sign(secret: str, method: str, path: str, body: bytes, ts: int | None = None) -> dict:
    """Headers for one gateway request; `body` is the exact bytes that will be sent."""
    ts = int(time.time()) if ts is None else ts
    digest = hashlib.sha256(body).hexdigest()
    message = f"{ts}.{method.upper()}.{path}.{digest}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {"X-GP-Timestamp": str(ts), "X-GP-Signature": f"v1={signature}"}
```

The brain checks, in this order:

1. No bearer token and a signature header missing: **401 `unauthorized`**.
2. Timestamp is not digits, or the signature is not `v1=` plus 64 lowercase hex characters: **401 `bad_signature`**.
3. The brain recomputes the signature over the raw body bytes it received and compares in constant time
   (`hmac.compare_digest`). Mismatch: **401 `bad_signature`**.
4. More than **120 s** between the timestamp and the brain's clock, in either direction: **401 `stale_timestamp`**.
   Exactly 120 s is accepted.
5. Gateway credentials are for the phone channel only: a start body with `"channel": "web"` gets **401
   `unauthorized`**.

Sign the bytes you send. Serializing the body again after signing (different spaces, escaped or raw UTF-8) changes
the bytes and breaks the signature. [`hmac_vectors.json`](../contracts/examples/hmac_vectors.json) shows both cases.

### 3.2 Web (talk page): bearer token

1. The page calls `POST /api/web/sessions` with `{"lang": "es"}` (no auth; more than 20 per hour from one IP address
   gets **429 `rate_limited`**). The answer is `{"call_id", "token", "expires_at"}`.
2. The page sends `Authorization: Bearer <token>` on `/start`, `/turn` and `/end` for that `call_id`. The token is
   valid for 30 minutes and only for the `web` channel.

A missing, unknown or expired token, a token issued for another `call_id`, or a start body with
`"channel": "phone"` gets **401 `unauthorized`**. The browser never holds the gateway secret.

---

## 4. Calls, `seq` and idempotency

```
POST start (seq 0)  →  POST turn (seq 1)  →  POST turn (seq 2)  →  …  →  POST end
```

- **`/start`** is sent once when the call begins. Its reply is the opening disclosure and consent question. A repeated
  `/start` for the same `call_id` returns the stored first reply.
- **`/turn`** carries one event. `seq` goes up by 1 with every turn request (utterance, dtmf or silence):
  - the same `seq` as the last accepted turn: the brain returns the **identical stored reply** without processing it
    again, and does not compare bodies. This is what makes a retry safe;
  - a `seq` lower than the last accepted turn: **409 `stale_seq`**;
  - a higher `seq`: processed. Gaps are accepted (a lost request is not waited for);
  - a request rejected with 401 or 422 does not use up its `seq`.
- **`/end`** is sent once, when the call is over, possibly while `/start` is still being processed. The answer is
  `{}`; a second `/end` changes nothing and also gets `{}`.
- **One request at a time.** The brain handles requests for the same `call_id` one after another, in the order they
  arrive. An `/end` that arrives while `/start` is running is applied after it.
- **After the end.** Once the brain has sent `end: true`, a new `/turn` gets an empty closing reply (`say: ""`,
  `ask: null`, `end: true`, the same `end_reason`). After `/end`, a `/turn` gets **409 `conflict`**.
- **Unknown calls.** `/turn` or `/end` for a `call_id` that was never started: **404 `unknown_call`**.
- **Idle calls.** The brain closes a call that has had no request for 10 minutes, as if `/end` had arrived with
  reason `timeout`; later turns get **409 `conflict`**.

---

## 5. Requests

### 5.1 StartRequest

```json
{"v": 1, "seq": 0, "channel": "phone", "lang": "en", "test": false}
```

| Field | Type | Meaning |
|---|---|---|
| `v` | `1` | API version. Required. |
| `seq` | `0` | Always 0 for start. Required. |
| `channel` | `"phone"` \| `"web"` | Must match the credentials (signature = phone, bearer token = web). Required. |
| `lang` | `"en"` \| `"es"` | Phone: always `en`. Web: the language the student picked. Required. |
| `test` | boolean, default `false` | `true` for a test call placed by the team, not by a student. |

### 5.2 TurnRequest

Exactly one event per request (three separate request bodies):

```text
{"v": 1, "seq": 7, "lang": "en", "event": "utterance", "text": "I make about 900 a month",
 "masked": false, "confidence": 0.93, "interrupted": false, "typed": false}
{"v": 1, "seq": 8, "lang": "en", "event": "dtmf", "dtmf": "1"}
{"v": 1, "seq": 9, "lang": "en", "event": "silence", "silence_n": 1, "silence_ms": 5000}
```

| Field | Event | Type | Meaning |
|---|---|---|---|
| `v` | all | `1` | API version. Required. |
| `seq` | all | integer ≥ 1 | 1 for the first turn, then +1 per turn request. Required. |
| `lang` | all | `"en"` \| `"es"` | Language of the text. Phone: always `en`. Web: the page's current language. Default: the call's language. |
| `event` | all | `"utterance"` \| `"dtmf"` \| `"silence"` | What happened. Required. |
| `text` | utterance | string, ≤ 1000 characters | The final transcript (or typed text). Required for `utterance`. No partial transcripts. An empty text is treated as unclear and the question is asked again. |
| `masked` | utterance | boolean, default `false` | Phone: `true` when the gateway replaced a run of 9 or more digits (SSN, phone or card number) with `#` characters. The number of `#` characters means nothing. |
| `confidence` | utterance | number 0–1 or `null` | How sure the transcript is; `null` when unknown. Below 0.75 the brain confirms a key money amount explicitly (work income, family cash, rent share, rent paid by others; `docs/SPEC.md` §3.4). |
| `interrupted` | utterance | boolean, default `false` | The student spoke over the previous reply. |
| `typed` | utterance | boolean, default `false` | The text was typed, not spoken: the talk page's typing mode and quick replies; on the phone only in test calls. It does not mark a test call (only `test` in StartRequest does). |
| `dtmf` | dtmf | string `^[0-9*#]{1,20}$` | The keypad key pressed. Required for `dtmf`. For yes/no questions, `1` = yes and `2` = no. See the keypad note below. |
| `silence_n` | silence | integer ≥ 1 | How many silence events in a row, counting from 1; any utterance or dtmf resets it. Required for `silence`. |
| `silence_ms` | silence | integer ≥ 0 | Approximate time since the student last spoke or pressed a key; it grows with `silence_n` (informational only). |

Fields that belong to another event are ignored. Silence is answered without the language model: the first
silence repeats the question, the second asks its closed form with the keypad option, the third ends the call
(`end_reason: "no_input"`) after giving the coordinator's number.

**Keypad.** The phone gateway sends every key press as its own `dtmf` event with exactly one key; it never collects
several keys into one event. GatorPlate uses single keys only: `1` = yes and `2` = no, and a closed choice offers at
most three single-key options ("press one, two, or three"). There is **no multi-key keypad entry** anywhere: amounts
are answered by voice, and a money question's closed form is a spoken band choice (never "type the amount, then
press pound"). The pattern allows up to 20 keys only for tolerance; the schema also describes how a brain could
collect a longer entry with empty replies, which GatorPlate v1 does not use. If a `dtmf` value ever carries more than
one key, the brain treats it as an unclear answer and asks the closed form again.

### 5.3 EndRequest

```json
{"v": 1, "reason": "completed", "turns": 9, "duration_ms": 118000}
```

| `reason` | When |
|---|---|
| `completed` | The client ended the call after a reply with `end: true, end_reason: "completed"`. |
| `declined` | The same, after `end_reason: "declined"` (the student did not consent). |
| `no_input` | The same, after `end_reason: "no_input"`, or the gateway ended a silent call on its own. |
| `caller_hangup` | The student hung up, or left the talk page. |
| `timeout` | Replies did not arrive in time; the gateway said the `fatal` line. |
| `max_duration` | The call reached its time limit; the gateway said the `time_limit` line. |
| `error` | Any other failure ended the call (including a failed `/start`). The brain treats `timeout` and `error` alike. |

`turns` is the number of student turns sent: utterance and dtmf requests, each `seq` counted once; silence events are
not counted. `duration_ms` is the call length. Both are optional and informational. If the call ends before a result
was given, the coordinator sees the case as incomplete.

---

## 6. BrainReply

The reply to `/start` and `/turn`. Every property is always present.

```json
{"say": "Got it — about nine hundred dollars a month from work.",
 "ask": "How much is your share of the rent each month?",
 "end": false, "end_reason": null, "lang": "en", "listen": "long", "expect": "number",
 "interruptible": true, "hold_s": 0, "display": null, "choices": null, "card_url": null, "debug": null}
```

| Field | Type | Meaning |
|---|---|---|
| `say` | string, may be `""` | The statement, spoken first. On `/start`: the opening disclosure (never empty). |
| `ask` | string or `null` | The question, spoken after `say`, or `null` when there is no question. Never `""`. The student may always interrupt `ask`. |
| `end` | boolean | `true`: say `say`, then hang up (phone) or close the conversation (web). |
| `end_reason` | `null` \| `"completed"` \| `"no_input"` \| `"declined"` | Set only when `end` is `true`. |
| `lang` | `"en"` \| `"es"` | The language to speak this reply in. Phone: `en`, or `es` for one Spanish notice (below). Web: the conversation language. |
| `listen` | `"normal"` \| `"long"` | `long` = wait more patiently for the end of the answer and allow a longer silence (amounts, slow talkers). |
| `expect` | `"open"` \| `"yes_no"` \| `"confirm"` \| `"number"` \| `"choice"` | The kind of answer `ask` expects. `confirm` = yes or no about a value just repeated back. `open` when `ask` is `null`. |
| `interruptible` | boolean | May the student cut off `say`? |
| `hold_s` | integer 0–60 | `0`, or 1–60 when the student asked to wait (see below). |
| `display` | string or `null` | Web only: on-screen text of this reply (`say` and `ask` together) with digits and symbols. |
| `choices` | array of 1–6 strings, or `null` | Web only: quick-reply labels for `ask`. |
| `card_url` | string or `null` | Web only: same-origin path of the student's card (`/c/<token>`) once it exists. |
| `debug` | object or `null` | `null` unless the brain runs with `GP_DEBUG_KEYS=1` (never in production): `{"keys": [sentence keys used], "phase": "<phase>"}`. |

Rules the schema cannot express on its own (the checker tests them on every example):

- **The `/start` reply** has a non-empty `say`, a consent question in `ask`, `end: false` and `interruptible: false`:
  the opening disclosure is never interruptible. On the phone it says that GatorPlate is an AI, student-built and not
  an official SF State service, that an AI turns what the student says into text to check CalFresh, and that the call
  audio isn't recorded; the question asks for consent with a keypad option. The examples and the sentence bank use
  this opening, exactly 40 words, with the keypad option in words ("press one", never "press 1"):
  "Hi, this is GatorPlate, a student-built AI assistant, not an official SF State service. An AI turns what you say
  into text to check CalFresh for you; the call audio isn't recorded." + "Okay to start? Say yes, or press one."
- **`end: true`** means: say `say`, then hang up. `ask` is `null`, `hold_s` is `0`, `interruptible` is `false`.
- **An empty reply** (`say: ""`, `ask: null`, `end: false`) means: say nothing and keep listening. The schema names a
  key that is part of a longer keypad entry as the example; GatorPlate v1 never asks for one (§5.2), but clients must
  still handle the shape.
- **`interruptible: false`** is also used for replies that state an amount or give a card code or a phone number, and
  for crisis resources, so that the county-decides sentence, the code or the number is heard in full.
- **`hold_s` 1–60** (the student said "hold on"): `ask` is `null`. The client keeps listening and sends no silence
  event for `hold_s` seconds; the student's next words arrive as a normal utterance. If the student is still silent
  when the hold ends, the client may say the last `ask` again; then silence events resume as usual.
- **Phone:** `display`, `choices` and `card_url` are always `null`; the gateway ignores them. `lang` is `en`, except
  that a student who asks for Spanish gets **one** reply with `lang: "es"` (spoken with a Spanish voice) that points to
  the web talk page; the next reply is English again. The phone conversation itself stays in English.
- **Web:** `display` is always a string. `card_url`, once set, stays set in every later reply of the call.
- `choices` only appear together with a question (`ask` not `null`).

---

## 7. Phone text rules and word budgets

`say` and `ask` on the phone are spoken exactly as written:

- Plain words. No symbols `$ % / ~ –` (en dash), no markdown, emoji or markup tags.
- Numbers in words: money as "three hundred six dollars"; phone numbers and codes digit by digit in groups
  ("four one five, three three eight, one two zero three"; "four eight one, two zero six"); keypad keys as
  "press one".
- Web addresses spoken: "gatorplate dot fly dot dev slash go".
- The web `display` uses digits and symbols ("$306 a month", "(415) 338-1203").
- Every estimated amount is followed in the same reply by the county-decides sentence ("The county makes the final
  decision.").
- Never, in any reply or language: a rejection ("not eligible", "ineligible", "don't qualify", "denied",
  "no califica", "no eres elegible"); a promise of a text message, a callback, a live transfer, a reminder message,
  or that anything was "sent to the coordinator"; a claim of relay-service support or of "any language"; an
  eligibility decision ("you qualify", "you are eligible", "approved"): only the county decides.

**Word budgets** count the words of `say` and `ask` together. A word is a whitespace-separated token that contains a
letter or a digit ("student-built" and "isn't" are one word each; a lone "—" is none).

| Reply | Max words | Which replies |
|---|---|---|
| Opening | 40 | The `/start` reply. |
| Question | 25 | Every reply that is not an opening or a result: an acknowledgement plus the next question, confirmations, re-asks, short notices, goodbyes without a phone number. |
| Result | 45 | A reply whose `say` gives an outcome or contact details to keep: the estimate or a routing result, the expedited outlook, the apply-today and card lines, or a phone number (coordinator, county, crisis). |

Card line on the phone, set by `GP_CARD_DELIVERY`: `screen` (at the demo table) says "Your card is ready — scan the
QR code on the screen."; `code` says "Go to gatorplate dot fly dot dev slash go and enter code" followed by the
6-digit code read digit by digit.

---

## 8. GatewayLines

`GET /v1/lines?lang=en` returns the lines the gateway says on its own. GatorPlate owns all of the wording. The
gateway fetches them when it boots, caches them, and keeps identical built-in copies for when the brain cannot be
reached. The English set is [`contracts/examples/lines_en.json`](../contracts/examples/lines_en.json):

| Key | When the gateway says it | English text |
|---|---|---|
| `filler` (3) | A turn reply (utterance or dtmf) has not arrived after 1.5 s. | "One moment." · "Let me check that." · "Okay, one second." |
| `retry` | First failure in a row; then it repeats the last `ask`. | "Sorry, I didn't catch that." |
| `fatal` | Second failure in a row; then it hangs up. | "Sorry, something went wrong on our side. You can reach the SF State CalFresh coordinator at four one five, three three eight, one two zero three. Goodbye." |
| `fatal_start` | `/start` failed; then it hangs up. Includes the AI disclosure. | "Hi, this is GatorPlate, a student-built AI assistant. Sorry, it isn't working right now. You can reach the SF State CalFresh coordinator at four one five, three three eight, one two zero three. Goodbye." |
| `no_input_bye` | The gateway ends a silent call on its own. | "I can't hear you, so I'll hang up now. You can call back anytime. Goodbye." |
| `time_limit` | The call reached its time limit; then it hangs up (`max_duration`). | "We've reached the time limit for this call. Your answers so far are saved for the coordinator. Goodbye." |
| `line_unavailable` | The phone line cannot take a call right now (for example, the team switched it off). | "Hi, this is GatorPlate, a student-built AI assistant for SF State students. The line isn't available right now. You can reach the SF State CalFresh coordinator at four one five, three three eight, one two zero three. Goodbye." |

`lang=es` returns the same keys in Spanish; any other `lang` gets **422 `invalid_request`**.

---

## 9. Time budgets and failures

One set of budgets, used by every test gate:

| Request | Gateway budget (total, including at most one retry) | Brain target (server processing) |
|---|---|---|
| `/start` | 3.0 s | under 50 ms; never calls the language model |
| `/end` | 3.0 s, fire-and-forget | under 50 ms |
| `/v1/lines`, `/v1/health` | — | under 50 ms |
| `/turn` utterance or dtmf | 6.0 s; a `filler` line is said at 1.5 s | p50 ≤ 0.8 s, p95 ≤ 1.5 s. Language model timeout 2.3 s, then a closed question instead. Hard turn budget 2.6 s. |
| `/turn` silence | 2.5 s, no filler | under 100 ms; no language model |

- **Retry.** The gateway retries a request once, only after a connection error or a 502/503/504 status, and only with
  at least 2 s of its budget left. A retry sends the same request again with the same `seq`, so the brain answers it
  from the stored reply if the first attempt was processed.
- **Failure ladder.** A request fails when no usable 200 reply arrives within the budget. First failure in a row:
  the gateway says `retry`, then the last `ask` again. Second failure in a row: it says `fatal` and hangs up. A
  failed `/start`: it says `fatal_start` and hangs up. Any successful reply resets the count. A failed silence request
  may be answered by the gateway on its own: it repeats the last `ask`, and at the third silence in a row it says
  `no_input_bye` and hangs up (`/end` reason `no_input`).

---

## 10. Web channel

- The talk page creates a session (`POST /api/web/sessions`), then uses the same `/start`, `/turn` and `/end`
  endpoints with its bearer token and `"channel": "web"`.
- It speaks `say` and then `ask` with the browser's voice in the reply's `lang`, and shows `display`. When
  `interruptible` is `false` it offers no tap-to-interrupt while `say` is spoken.
- The web opening (`/start` reply) says that the student's browser turns their voice into text and names the speech
  service of each supported browser ("Chrome uses Google's speech service; Safari uses Apple's"). This is a privacy
  fact and the only place where GatorPlate's text names companies.
- `choices` become buttons; a tap sends the label as an utterance with `typed: true`.
- When `card_url` is set, the page shows an "Open my card" button that opens that path. The talk page shows no QR
  code (there is no QR endpoint for a card token); at the demo table the card QR is on the coordinator console.
- The page sends only utterance events (spoken or typed). `confidence` is the browser's value when it has one, else
  `null`; `masked` is always `false`, because the brain itself redacts digits (see below).
- After a reply with `end: true` the page sends `/end` with the same reason; if the student leaves early it sends
  `caller_hangup` (best effort).

---

## 11. Privacy in the contract

- No request ever contains audio or the student's phone number (or anything derived from it).
- On the phone, `masked: true` means the gateway already replaced a run of 9 or more digits with `#`.
- The brain redacts again before anything else sees the text: 9 or more written digits, 7 or more spoken digits,
  and 13–19-digit card-like runs. On the web this is the only protection.
- Masked or redacted digits get Social Security number or card-number guidance, then the pending question again. A
  run of 13–19 digits gets the card-number guidance, every other run the Social Security number guidance. A masked
  run has no digit count (the number of `#` means nothing), so it gets the card-number guidance when the utterance
  mentions a card or a bank account, and the Social Security number guidance otherwise. The digits are never stored;
  the case records only that something was blocked.
- The brain does not write request or reply text to its logs.

---

## 12. Errors

Every non-200 response has this body:

```json
{"error": {"code": "stale_seq", "message": "seq is older than the last accepted turn.", "retryable": false}}
```

`message` is short and generic (no stack traces, no request text). `retryable` is `true` when sending the same request
again later may succeed.

| Code | HTTP | `retryable` | When |
|---|---|---|---|
| `unknown_call` | 404 | false | `/turn` or `/end` for a `call_id` that was never started |
| `bad_signature` | 401 | false | gateway signature malformed or wrong |
| `stale_timestamp` | 401 | false | gateway timestamp more than 120 s from the brain's clock |
| `unauthorized` | 401 | false | no credentials; bad, expired or other-call bearer token; channel not allowed for the credentials |
| `rate_limited` | 429 | true | more than 20 web sessions per hour from one IP address |
| `invalid_request` | 422 | false | body not JSON or not matching the request schema; malformed `call_id`; unsupported `lang` |
| `stale_seq` | 409 | false | turn `seq` lower than the last accepted turn |
| `conflict` | 409 | false | turn for a call that has already ended |
| `internal` | 500 | true | unexpected brain failure; sending the same `seq` again is safe |
| `locked`, `not_found`, `gone` | 409, 404, 410 | false | shared code list; not used by these endpoints |

---

## 13. Versioning

- Every request body carries `"v": 1` and every path starts with `/v1`.
- Inside v1 only one kind of change is allowed: a new optional request field (receivers ignore unknown fields).
- Anything else (a reply field, an enum value, an error code, the signing rules, the meaning of a field) needs a new
  version: `/v2` paths and `"v": 2`, with the old version kept until both clients have moved.

---

## 14. Examples and the checker

The files in [`contracts/examples/`](../contracts/examples/) are the shared test vectors for both sides of the API.
Reply wording in them is **illustrative** (`"illustrative_text": true`): the sentence bank owns the final wording,
but every example follows the phone text rules and word budgets. Files with Spanish student text are marked
`"native_review": true`.

| File | What it shows |
|---|---|
| `maria_phone.json` | The main phone demo (golden dialogue `maria_g1`): consent, five questions, one flip question, result about $306 a month, expedited cash question, apply-today and card lines, goodbye. Ends with the outcome the brain must reach. |
| `sofia_web_es.json` | A Spanish web call: session, bearer token, consent with `choices`, routing to the coordinator (under 22 and living with a parent), `display`, `card_url`. |
| `jamal_phone_expedited.json` | A phone call for a student staying on a friend's couch with no income: about $306 a month, expedited service possible, the card code read aloud (`GP_CARD_DELIVERY=code`), a reply with `ask: null`. |
| `edge_cases.json` | Keypad consent, consent declined (voice and keypad), masked digits, three silences, repeated and stale `seq`, unknown call, bad signature, stale timestamp, hold, Spanish on the phone, schema errors, web token errors, rate limit, turns after the end, health, web redaction, explicit amount confirm, interruption, crisis. |
| `lines_en.json` | The exact English `GatewayLines`. |
| `hmac_vectors.json` | Signing vectors (start, turn, end, lines; raw and escaped UTF-8; different whitespace) and checks (query string signed, upper-case hex, missing `v1=`, wrong secret, re-serialized body, fractional timestamp, missing headers, window edges). The secret `test-secret-do-not-use` is a public test value. |

**Delivery modes.** The phone card line depends on the server setting `GP_CARD_DELIVERY`, so a replay never mixes
modes in one server run: each scenario that declares `settings.GP_CARD_DELIVERY` is replayed against a server started
in that mode (`maria_phone.json`: `screen`; `jamal_phone_expedited.json`: `code`), one server per mode. Scenarios
without that setting never reach a phone card line and may run in either mode.

**Example file format.** Each dialogue file has `scenarios[]`. A scenario has `id`, `title`, `channel`, `lang`,
`call_id`, optional `settings` (`GP_CARD_DELIVERY`, `GP_DEBUG_KEYS`), optional `given` (the call state before the
first exchange: `started`, `last_seq`, `student_turns`, `pending` question, `ended_by_brain`), optional `server_now` (the brain's clock
for explicit auth headers), `exchanges[]` and optional `expect_final` (the outcome the brain's own end-to-end tests
check; those names are descriptive, not part of this API). An exchange has:

- `step`: `start`, `turn`, `end`, `lines`, `health` or `web_session`;
- `request`: `method`, `path`, optional `query`, `auth` (`gateway`, `bearer` or `none`), optional `headers`, and
  `body` (a JSON value) or `body_raw` (the exact string sent), plus `valid: false` when the body is meant to fail
  the schema. `auth: "gateway"` without `headers` means "sign normally"; with `headers` it gives the exact headers
  of an auth test, verified with the secret in `hmac_vectors.json` and the scenario's `server_now`;
- `response`: `status` and `body` (or `body_ref`, a file in the same folder);
- `keys`: the sentence keys used for the reply (equal to `debug.keys` when `GP_DEBUG_KEYS=1`);
- `budget` (phone replies): `opening`, `question` or `result`;
- optional `id`, `same_as` (this reply must be identical to an earlier exchange's reply) and `note`.

**Checker.** `python3 contracts/check_examples.py` (standard library only; `-v` prints one line per scenario) checks
that the schema uses only supported keywords, validates every request and response body against the schema,
recomputes every HMAC vector and auth header, replays the `seq` rules, and tests the phone text rules, word budgets
(the `result` budget only for a reply with a result line or a phone number), the phone opening elements, one key per
phone `dtmf` event, `/end` `turns`, reply rules and the error table. It exits with status 1 on any problem.
