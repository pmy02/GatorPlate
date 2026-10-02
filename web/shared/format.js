// GatorPlate display formatting (docs/UI_SPEC.md A4.7, A6.3). Pacific Time everywhere; locales en-US and es-US.
// Amounts arrive as whole dollars (numbers) or money strings ("1169.10"); the UI never computes an amount.

export const TZ = "America/Los_Angeles";
const LOCALE = { en: "en-US", es: "es-US" };
const loc = (lang) => LOCALE[lang] || LOCALE.en;

// "$306", "$1,100"; cents only when asked and present ("$18.50").
export function money(value, { cents = false } = {}) {
  if (value === null || value === undefined || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "";
  const whole = !cents || Number.isInteger(n);
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2 });
}

// A date-only string ("2026-10-05") is a calendar date, never shifted by time zones.
function toDate(value) {
  if (value instanceof Date) return { d: value, dateOnly: false };
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return { d: new Date(`${value}T12:00:00Z`), dateOnly: true };
  return { d: new Date(value), dateOnly: false };
}

function fmt(value, lang, options) {
  if (!value) return "";
  const { d, dateOnly } = toDate(value);
  return new Intl.DateTimeFormat(loc(lang), { ...options, timeZone: dateOnly ? "UTC" : TZ }).format(d);
}

export const time = (value, lang = "en") => fmt(value, lang, { hour: "numeric", minute: "2-digit" });
export const day = (value, lang = "en") => fmt(value, lang, { weekday: "short", month: "short", day: "numeric" });
export const monthDay = (value, lang = "en") => fmt(value, lang, { month: "long", day: "numeric" });
export const dateTime = (value, lang = "en") => `${day(value, lang)}, ${time(value, lang)}`;

// The Pacific calendar date of an instant, as "YYYY-MM-DD".
export function pacificDate(value = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date(value));
  return parts;
}

// Whole days from today (Pacific) to a date-only string; negative when past.
export function daysUntil(dateOnly, now = new Date()) {
  const a = Date.parse(`${pacificDate(now)}T00:00:00Z`);
  const b = Date.parse(`${dateOnly}T00:00:00Z`);
  return Math.round((b - a) / 86400000);
}

// "(415) 338-1203" from any 10-digit form; other text is returned as given.
export function phone(value) {
  const digits = String(value || "").replace(/\D/g, "").replace(/^1(?=\d{10}$)/, "");
  return digits.length === 10 ? `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}` : String(value || "");
}

export const telHref = (value) => `tel:+1${String(value || "").replace(/\D/g, "").slice(-10)}`;

// Case codes are shown as given ("K7Q-2FM", .code class); short codes in two groups ("481 206").
export const caseCode = (value) => String(value || "").toUpperCase();
export const shortCode = (value) => String(value || "").replace(/^(\d{3})(\d{3})$/, "$1 $2");
