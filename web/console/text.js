// Console wording (English only) and the pure formatters that compose it from data (docs/UI_SPEC.md A3.3-A3.12).
// The server sends codes, kinds and numbers; the reason and detail sentences come from the server as written.
// No DOM here: this module is imported by the views and by the node unit tests.
import { money, time, day, daysUntil } from "../shared/format.js";

export const TIERS = {
  likely: { label: "Likely", icon: "i-check-circle", cls: "chip--likely" },
  coordinator: { label: "Coordinator check", icon: "i-person", cls: "chip--coordinator" },
  other_help: { label: "Other help", icon: "i-heart-hand", cls: "chip--other" },
};

export const REASON_LABELS = {
  likely: "Likely",
  "coordinator.parent_household": "Under 22, lives with a parent",
  "coordinator.shared_household": "Shares food with others",
  "coordinator.grad_no_exemption": "Grad student — no exemption found",
  "coordinator.not_degree": "Not in a degree program",
  "coordinator.age_outside_student_rule": "Age outside the student rule",
  "coordinator.gig_income": "Self-employment income",
  "coordinator.boarder": "Pays for room and meals",
  "coordinator.spouse_student": "Spouse is also a student",
  "coordinator.status_complex": "Status question — needs a person",
  "coordinator.elderly_disabled": "Age or disability rules — needs a person",
  "coordinator.unresolved": "An answer that changes the result is open",
  "other_help.status": "Status-related — other help offered",
  "other_help.over_gross_limit": "Income above the gross limit",
  "other_help.dorm_meal_plan": "Dorm meal plan over 10 meals a week",
  "other_help.not_sfsu": "Not an SF State student",
  "other_help.zero_benefit": "Estimate is $0 — other help offered",
  "info.already_receiving": "Already gets CalFresh",
  "info.interview_waiting": "Waiting for the county interview",
};

export const reasonLabel = (code) => REASON_LABELS[code] || (code ? "Needs a person" : "");

export const STATUS_LABELS = {
  new: "New",
  reviewed: "Reviewed",
  applied: "Applied",
  interview_scheduled: "Interview set",
  approved: "Approved",
  follow_up: "Follow up",
};

// Answer groups and slot labels (A3.5). The labels come from ConsoleMeta.slot_specs; these are the same words, used
// only when a spec is missing.
export const SLOT_GROUPS = [
  ["Student", ["level", "units", "half_time", "grad_exemption", "ta_ra", "age"]],
  ["Household", ["lives_with_parent", "roommates", "roommates_count", "household_food", "dorm_on_campus",
    "meals_per_week", "dorm_meals_over_10", "spouse", "spouse_student", "children_count", "youngest_child_age",
    "boarder"]],
  ["Money", ["earned_monthly", "work_study_monthly", "gig_monthly", "unearned_monthly", "other_cash_monthly",
    "dependent_care_monthly"]],
  ["Housing", ["homeless", "homeless_shelter_cost_monthly", "rent_share", "rent_paid_by_others_to_landlord",
    "heat_cool", "other_utils"]],
  ["3-day check", ["cash_on_hand"]],
  ["Other", ["already_receiving", "applied_waiting_interview", "previously_denied", "income_changing_soon"]],
];

export const SLOT_LABELS = {
  level: "Student level", units: "Units this term", half_time: "Half-time or more",
  grad_exemption: "Grad student exemption", ta_ra: "TA or RA job", age: "Age",
  lives_with_parent: "Lives with a parent", roommates: "Lives with roommates", roommates_count: "Number of roommates",
  household_food: "Buys and cooks food", dorm_on_campus: "Lives in a campus dorm",
  meals_per_week: "Meal plan, meals a week", dorm_meals_over_10: "Meal plan over 10 meals a week",
  spouse: "Spouse or partner", spouse_student: "Spouse is a student", children_count: "Children",
  youngest_child_age: "Youngest child's age", boarder: "Pays for room and meals",
  earned_monthly: "Work income", work_study_monthly: "Work-study", gig_monthly: "Self-employment",
  unearned_monthly: "Other income", other_cash_monthly: "Cash from family or friends",
  dependent_care_monthly: "Child or dependent care", homeless: "No regular place to stay",
  homeless_shelter_cost_monthly: "Pays to stay", rent_share: "Rent share",
  rent_paid_by_others_to_landlord: "Rent paid by someone else", heat_cool: "Heating or cooling bill",
  other_utils: "Other utility bills", cash_on_hand: "Money on hand now", already_receiving: "Already gets CalFresh",
  applied_waiting_interview: "Applied, waiting for the interview", previously_denied: "Applied before",
  income_changing_soon: "Income changing soon", consent: "Consent",
};

// consent is shown in the header; the two routing-only slots are never shown (A3.5).
export const NOT_IN_ANSWERS = new Set(["consent", "volunteered_status", "elderly_or_disabled"]);

// The rules table's question-picker priority list (A3.10).
export const FLIP_CANDIDATES = ["household_food", "rent_paid_by_others_to_landlord", "other_cash_monthly",
  "earned_monthly", "heat_cool", "other_utils"];

// Live view: the answers a call usually fills, shown as pending rows ("—") until they arrive (A3.8).
export const LIVE_CORE = ["level", "units", "age", "lives_with_parent", "household_food", "earned_monthly",
  "other_cash_monthly", "rent_share", "rent_paid_by_others_to_landlord", "cash_on_hand"];

export function slotLabel(name, specs) {
  return (specs && specs[name] && specs[name].label) || SLOT_LABELS[name] || name;
}

export const SOURCES = {
  llm: { icon: "i-quote", label: "From the student's words" },
  parser: { icon: "i-quote", label: "From the student's words" },
  keypad: { icon: "i-keypad", label: "Phone keypad" },
  coordinator: { icon: "i-person-check", label: "Set by the coordinator" },
  default: { icon: "i-table", label: "Default assumption from the rules table" },
  seed: { tag: "Sample", label: "Sample data" },
};

export const STATES = {
  clear: { icon: "i-check", label: "Clear", cls: "state--clear" },
  assumed: { label: "Assumed", cls: "state--assumed" },
  unclear: { label: "Unclear", cls: "state--unclear" },
  missing: { label: "—", cls: "state--missing" },
};

export const capFirst = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");

// ---------------------------------------------------------------- reason chips (A3.10)

export const NEVER_ASKED = "Never asked — Social Security number · immigration status";
export const ANSWERED_BEFORE = "Answered before we asked — no question needed";

// {text, style: "outcome" | "routine"}
export function askedChip(a) {
  if (!a) return null;
  if (a.kind === "flip" || (a.reason && a.kind !== "standard")) {
    return { text: `Why this question? ${capFirst(a.reason || "could change the result")}`, style: "outcome" };
  }
  if (a.key === "expedited.intro_cash") return { text: "Checks 3-day benefits", style: "routine" };
  if (a.kind === "confirm") return { text: "Repeated back to confirm a key number", style: "routine" };
  if (a.kind === "band") return { text: "Asked for a range — the exact amount wasn't known", style: "routine" };
  if (a.kind === "closed" || a.kind === "reprompt") return { text: "Asked again in a simpler form", style: "routine" };
  return { text: "Needed for any estimate", style: "routine" };
}

// The live "Now asking — why" chip from an event's sentence key and asked_reason.
export function nowAskingChip(key, reason) {
  if (reason) return { text: `Why this question? ${capFirst(reason)}`, style: "outcome" };
  if (!key) return null;
  if (key === "expedited.intro_cash") return { text: "Checks 3-day benefits", style: "routine" };
  if (key.startsWith("confirm.")) return { text: "Repeated back to confirm a key number", style: "routine" };
  if (key.startsWith("reprompt.") || key.endsWith(".closed")) return { text: "Asked again in a simpler form", style: "routine" };
  if (key.startsWith("ask.") || key.startsWith("flip.")) return { text: "Needed for any estimate", style: "routine" };
  return null;
}

// {text, maxQuestions} or null (hard_stop and not_applicable are not shown).
export function skippedChip(s) {
  if (!s || s.reason === "hard_stop" || s.reason === "not_applicable") return null;
  return { text: s.detail || "Not asked — wouldn't change the result", maxQuestions: s.reason === "max_questions" };
}

// Flip-candidate slots the student answered without an asked[] entry listing them.
export function answeredBeforeAsked(c) {
  if (!c || !c.slots) return [];
  const asked = new Set((c.asked || []).flatMap((a) => a.slots || []));
  const studentSources = new Set(["llm", "parser", "keypad", "seed"]);
  return FLIP_CANDIDATES.filter((name) => {
    const s = c.slots[name];
    return s && s.state !== "missing" && studentSources.has(s.source) && !asked.has(name);
  });
}

export function askedCounter(summary) {
  const n = (summary && summary.asked_count) || 0;
  const m = (summary && summary.skipped_count) || 0;
  return `Asked ${n} · Not asked ${m} (wouldn't change the result)`;
}

// ---------------------------------------------------------------- yellow lines and the lock (A3.6)

export function effectText(effect) {
  if (!effect) return null;
  if (effect.kind === "amount") return `Could change the estimate by ${money(effect.delta_usd || 0)}`;
  if (effect.kind === "tier") return "Could change the result to Coordinator check";
  if (effect.kind === "expedited") return "Could change 3-day benefits";
  return null;
}

export const lockReason = (n) => `Check ${n} line${n === 1 ? "" : "s"} first`;
export const LOCK_LIVE = "Available after the call ends";
export const checkedAt = (at) => `Checked · ${time(at)}`;
export const reviewedAt = (at) => (at ? `Reviewed · ${time(at)}` : "Reviewed");

// ---------------------------------------------------------------- amounts and dates

export const perMonth = (n) => `${money(n)}/mo`;
export const spokenMonthly = (n) => `${n} dollars a month`;

// "$306" + "a month", or "at least about $306" for a floor (A3.5 item 2).
export function estimateParts(amount, isFloor) {
  if (amount === null || amount === undefined) return null;
  return { prefix: isFloor ? "at least about" : "", amount: money(amount), suffix: "a month",
    spoken: `${isFloor ? "at least about " : ""}${spokenMonthly(amount)}` };
}

export function firstMonthText(fm) {
  if (!fm) return null;
  const when = day(fm.filed_on);
  if (!fm.amount) return `If filed now (estimate): counts from ${when} — too few days left in ${fm.month_label} for a first-month amount`;
  return `If filed now (estimate): counts from ${when} — about ${money(fm.amount)} for ${fm.month_label}`;
}

export function expeditedChip(outlook) {
  if (outlook === "yes") return "3-day benefits possible";
  if (outlook === "maybe") return "3-day benefits: maybe";
  return null;
}

// "1:52" (minutes:seconds) and "01:12" (the live clock).
export function minSec(ms, pad = false) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = String(total % 60).padStart(2, "0");
  return `${pad ? String(m).padStart(2, "0") : m}:${s}`;
}

// Call length: created_at to the last timeline point (A3.5 item 1).
export function callDuration(c) {
  if (!c) return "";
  const points = (c.timeline || []).map((p) => Date.parse(p.at)).filter(Number.isFinite);
  if (!points.length) return "";
  return minSec(Math.max(...points) - Date.parse(c.created_at));
}

// Deadline countdown chip (A3.9): neutral above 7 days, amber at 7 or less, bold amber with an hourglass at 2 or less.
export function countdown(dateOnly, now = new Date()) {
  if (!dateOnly) return null;
  const d = daysUntil(dateOnly, now);
  if (d < 0) return { text: `${-d} day${d === -1 ? "" : "s"} past due`, level: "urgent" };
  if (d === 0) return { text: "Due today", level: "urgent" };
  if (d <= 2) return { text: `Due in ${d} day${d === 1 ? "" : "s"}`, level: "urgent" };
  return { text: `${d} days left`, level: d <= 7 ? "soon" : "neutral" };
}

// Same step as the card's interview block (data/content/card.en.json): call right away; no deadline is claimed.
export const INTERVIEW_MISSED = "Interview missed — the student should call the county at (855) 355-5757 right away to set "
  + "a new time.";

// "Rules FY2027 · in effect Oct 1, 2026" (A3.3).
export function rulesPill(rules) {
  if (!rules) return "Rules";
  const fy = (String(rules.label || rules.table_id || "").match(/FY\s?\d{4}/) || [""])[0].replace(/\s/g, "");
  return `Rules ${fy || rules.table_id} · in effect ${longDate(rules.effective_from)}`;
}

// "Oct 1, 2026" from a date-only string.
export function longDate(dateOnly) {
  if (!dateOnly) return "";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${String(dateOnly).slice(0, 10)}T12:00:00Z`));
}

// A source line: "Title, date" from a list of SourceRef. The short form keeps the title up to its first clause
// ("CDSS All County Letter 26-25, 2026-04-13"); the rules drawer lists every full title.
export function sourceText(id, sources, { short = false } = {}) {
  const s = (sources || []).find((x) => x.id === id);
  if (!s) return id || "";
  const title = (short ? shortTitle(s.title) : s.title).replace(/^GatorPlate\b/, "refriGator");
  return `${title}, ${s.date}`;
}

export function shortTitle(title) {
  const t = String(title || "");
  let cut = t.length;
  const colon = t.indexOf(": ");
  if (colon >= 8) cut = colon;
  for (const mark of [" (", ", ", "; "]) {
    const i = t.indexOf(mark);
    if (i > 0 && i < cut) cut = i;
  }
  // a sentence end after a full word, never an abbreviation ("H.R. 1", "Rev. Proc. 2025-32")
  const stop = /(?<=[a-z]{4,})\. /.exec(t);
  if (stop && stop.index > 0 && stop.index < cut) cut = stop.index;
  const out = t.slice(0, cut).trim();
  return out.length > 56 ? `${out.slice(0, 55).trim()}…` : out;
}

// A value the coordinator sees for a stored canonical value ("900.00" → "$900").
export function canonicalDisplay(raw, type) {
  if (raw === null || raw === undefined) return "";
  if (type === "money" || /^-?\d+\.\d{2}$/.test(raw)) {
    const [whole, cents] = String(raw).split(".");
    return cents && cents !== "00" ? money(`${whole}.${cents}`, { cents: true }) : money(Number(whole));
  }
  if (raw === "true") return "Yes";
  if (raw === "false") return "No";
  return String(raw);
}

// The coordinator's typed value → the canonical string, or null when it does not parse (string work, no float).
export function encodeEdit(type, input) {
  const v = String(input ?? "").trim();
  if (type === "bool") return v === "true" || v === "false" ? v : null;
  if (type === "int") return /^\d{1,4}$/.test(v) ? String(Number(v)) : null;
  if (type === "money") {
    const m = v.replace(/[$,\s]/g, "").match(/^(\d{1,7})(?:\.(\d{1,2}))?$/);
    if (!m) return null;
    return `${String(Number(m[1]))}.${(m[2] || "").padEnd(2, "0")}`;
  }
  return v ? v : null;
}

// ---------------------------------------------------------------- the programs part (section 6b, A3.5)

export const PROGRAMS_TITLE = "More money (estimates)";
export const programsHeader = (checked) => `Computed by the programs table — not by AI · checked ${longDate(checked)}`;

export const PROGRAM_STATUS = {
  likely: "Likely", maybe: "Maybe", check: "Check", coverage: "Coverage", zero: "Not counted", note: "Note",
};

const floorTen = (n) => n - (n % 10);

// Per year: a counted line's display value, a check range as "$90–$440", otherwise "—".
export function programPerYear(line) {
  if (!line) return "—";
  if (line.counted && line.display_yearly !== null && line.display_yearly !== undefined) return money(line.display_yearly);
  if (line.status === "check" && line.range_lo !== null && line.range_lo !== undefined
    && line.range_hi !== null && line.range_hi !== undefined) {
    return `${money(floorTen(line.range_lo))}–${money(floorTen(line.range_hi))}`;
  }
  return "—";
}

// Program names come from ConsoleMeta.programs.names; the footer uses the name without its parenthesis, and tax
// credits in lower case ("maybe tax credits $200").
const FOOTER_NAMES = { tax_credits: "tax credits" };
export function programName(id, names) {
  return (names && names[id]) || id;
}
function footerName(id, names) {
  return FOOTER_NAMES[id] || programName(id, names).replace(/\s*\([^)]*\)\s*$/, "");
}

// "Found about $4,220 a year (CalFresh $3,670 + 3 programs) · not counted: Medi-Cal coverage, maybe tax credits $200"
export function programsFooter(p, names) {
  if (!p || p.mode !== "full" || p.found_display === null || p.found_display === undefined) return null;
  const lines = p.lines || [];
  const key = lines.find((l) => l.id === "calfresh");
  const calfresh = key && key.display_yearly !== null && key.display_yearly !== undefined ? key.display_yearly
    : (p.calfresh_yearly === null || p.calfresh_yearly === undefined ? null : floorTen(p.calfresh_yearly));
  const others = lines.filter((l) => l.counted && l.id !== "calfresh").length;
  const parts = [];
  if (calfresh !== null) parts.push(`${programName("calfresh", names)} ${money(calfresh)}`);
  let head = `Found about ${money(p.found_display)} a year`;
  if (parts.length) head += ` (${parts[0]}${others ? ` + ${others} program${others === 1 ? "" : "s"}` : ""})`;
  const notCounted = [];
  for (const l of lines) {
    if (l.counted || l.id === "calfresh") continue;
    if (l.status === "coverage") notCounted.push(`${footerName(l.id, names)} coverage`);
    else if (l.status === "maybe") {
      const v = l.display_yearly ? ` ${money(l.display_yearly)}` : "";
      notCounted.push(`maybe ${footerName(l.id, names)}${v}`);
    } else if (l.status === "check") notCounted.push(`${footerName(l.id, names)} to check`);
  }
  return notCounted.length ? `${head} · not counted: ${notCounted.join(", ")}` : head;
}

// "Programs to check with the student: Medi-Cal (family income) · Clipper START"
export function listOnlyLine(p, names) {
  if (!p || p.mode !== "list_only") return null;
  const items = (p.lines || []).map((l) => {
    const n = footerName(l.id, names);
    return (l.note_keys || []).includes("medi_cal.family_income") ? `${n} (family income)` : n;
  });
  if (!items.length) return null;
  return `Programs to check with the student: ${items.join(" · ")}`;
}

export const foundPerYear = (n) => `Found about ${money(n)}/yr`;
export const appliedText = (at) => (at ? `Applied ${time(at)}` : "Applied");

// "From the card" (A3.5): labels for the card questions and their choices (console only).
export const CARD_QUESTIONS = {
  break_transit: { label: "Rides over breaks", choices: { none: "no, or away", two_days: "1–2 days a week",
    weekdays_muni: "most weekdays (Muni)", weekdays_bart: "most weekdays (with BART)" } },
  tax_dependent: { label: "Tax dependent", choices: { no: "no", yes: "yes", not_sure: "not sure" } },
  pge_bill: { label: "PG&E bill", choices: { own_mine: "student's name", own_roommate: "roommate's name",
    in_rent: "in the rent", not_sure: "not sure" } },
};

// {text, sample} — "Rides over breaks: most weekdays (Muni) · Tax dependent: no · PG&E bill: roommate's name — from
// the card, 4:12 PM"; seed answers end "— sample answers".
export function fromCardLine(answers, order = Object.keys(CARD_QUESTIONS)) {
  const entries = Object.entries(answers || {});
  if (!entries.length) return null;
  const rank = (id) => { const i = order.indexOf(id); return i < 0 ? order.length : i; };
  entries.sort((a, b) => rank(a[0]) - rank(b[0]));
  const parts = entries.map(([q, a]) => {
    const spec = CARD_QUESTIONS[q];
    const label = spec ? spec.label : q;
    const choice = spec && spec.choices[a.value] ? spec.choices[a.value] : a.value;
    return `${label}: ${choice}`;
  });
  const sample = entries.every(([, a]) => a.source === "seed");
  const newest = entries.map(([, a]) => a.at).filter(Boolean).sort((x, y) => Date.parse(y) - Date.parse(x))[0];
  const tail = sample ? "sample answers" : `from the card${newest ? `, ${time(newest)}` : ""}`;
  return { text: `${parts.join(" · ")} — ${tail}`, sample };
}

// ---------------------------------------------------------------- live view chips (A3.8)

export function privacyChip(ev) {
  const what = ev.kind === "card_number_blocked" ? "Card number blocked — not saved" : "SSN blocked — not saved";
  return ev.at ? `${what} · ${time(ev.at)}` : what;
}

const LANG_NAMES = { es: "Spanish", en: "English" };
export function languageChip(lr) {
  if (!lr) return null;
  const name = LANG_NAMES[lr.asked] || "Another language";
  if (lr.offered === "web") return `${name} requested — web page offered`;
  if (lr.offered === "switched") return `${name} requested — switched`;
  return `${name} requested`;
}

export const FLAG_CHIPS = {
  human_requested: "Asked for a person",
  crisis_resources_given: "Safety message given",
  closed_mode: "Simple questions mode",
};

export function rangeLabel(range) {
  if (!range) return "Estimate appears after income and rent";
  if (range.settled || range.lo === range.hi) return `${money(range.hi)} a month`;
  return `Between ${money(range.lo)} and ${money(range.hi)} a month`;
}

export const answersKept = (n) => `Conversation cleared — not saved. ${n} answer${n === 1 ? "" : "s"} kept.`;
export const callEnded = (dur) => (dur ? `Call ended · ${dur}` : "Call ended");

// Number of slots with a value (the end notice's {n}).
export function filledCount(c) {
  return Object.entries((c && c.slots) || {}).filter(([k, s]) => !NOT_IN_ANSWERS.has(k) || k === "consent")
    .filter(([, s]) => s && s.state !== "missing" && s.value !== null && s.value !== undefined).length;
}

// Case list row helpers (A3.4).
export const yellowBadge = (n) => `${n} to check`;
export function listTime(c, now = new Date()) {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(now);
  const d = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(new Date(c.created_at));
  if (d === today) return time(c.created_at);
  const md = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "America/Los_Angeles" })
    .format(new Date(c.created_at));
  return `${md}, ${time(c.created_at)}`;
}

export function emptyText(phoneDisplay) {
  return phoneDisplay
    ? `No calls yet. When a student calls ${phoneDisplay} or opens the talk page, the case appears here live.`
    : "No calls yet. When a student opens the talk page, the case appears here live.";
}

export const resetResult = (deleted) => `Reset · removed ${deleted}, samples restored`;
export const seedResult = (seeded) => `Samples seeded · ${seeded}`;
export const OFFLINE = (last) => `Can't reach the server — retrying. Cases are saved on the server.${last ? ` Last update ${last}.` : ""}`;
export const RULES_INVALID = "Rules table not valid for today — estimates paused.";
export const CONFLICT_TOAST = "This case changed — showing the latest.";

// ---------------------------------------------------------------- Pacific wall time for the tracking inputs

const PT_PARTS = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", hourCycle: "h23", year: "numeric",
  month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });

function ptParts(ms) {
  const out = {};
  for (const p of PT_PARTS.formatToParts(new Date(ms))) out[p.type] = p.value;
  return out;
}

// Minutes between Pacific wall time and UTC at an instant (-420 in October 2026).
export function ptOffsetMinutes(ms) {
  const p = ptParts(ms);
  const asUtc = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute), Number(p.second));
  return (asUtc - (ms - (ms % 1000))) / 60000;
}

// "2026-10-05T10:00" typed as Pacific time → "2026-10-05T17:00:00Z".
export function ptLocalToIso(local) {
  const m = String(local || "").match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return null;
  const wall = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]));
  let utc = wall - ptOffsetMinutes(wall) * 60000;
  utc = wall - ptOffsetMinutes(utc) * 60000;
  return new Date(utc).toISOString().replace(".000Z", "Z");
}

// An instant → "2026-10-05T10:00" in Pacific time (the value of a datetime-local input).
export function isoToPtLocal(iso) {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return "";
  const p = ptParts(ms);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
