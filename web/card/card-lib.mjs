// Card page helpers (docs/UI_SPEC.md A4); no DOM (node --test).

export function tokenFrom(path, search) {
  const q = new URLSearchParams(search).get("token");
  if (q && /^[\w-]{1,64}$/.test(q)) return q;
  const m = /^\/c\/([\w-]{8,64})\/?$/.exec(path);
  return m ? m[1] : null;
}

export const money = (n) => "$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

// [before, "$306", after] or null
export function splitAmount(text, amount) {
  if (amount === null || amount === undefined) return null;
  const a = money(amount);
  const i = text.indexOf(a);
  return i < 0 ? null : [text.slice(0, i), a, text.slice(i + a.length)];
}

// web addresses, the email, phones, 988 and 911 (not in "$1,911"; no lookbehind: older browsers)
const LINK = /(https?:\/\/[^\s)]*[^\s).,;:!?])|([\w.+-]+@[\w-]+(?:\.[\w-]+)+)|(\((\d{3})\) (\d{3})-(\d{4}))|(^|[^\w$,.])(988|911)\b/g;

export function segments(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(LINK)) {
    const start = m.index + (m[8] ? m[7].length : 0);
    if (start > last) out.push(text.slice(last, start));
    if (m[1]) out.push({ text: m[1].replace(/^https?:\/\//, ""), href: m[1], external: true });
    else if (m[2]) out.push({ text: m[2], href: `mailto:${m[2]}` });
    else if (m[3]) out.push({ text: m[3], href: `tel:+1${m[4]}${m[5]}${m[6]}` });
    else out.push({ text: m[8], href: `tel:${m[8]}` });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export const changed = (view, st) => st.tier !== view.tier || st.estimate_monthly !== view.estimate_monthly;

const fmt = (lang, opts, tz = "America/Los_Angeles") =>
  new Intl.DateTimeFormat(lang === "es" ? "es-US" : "en-US", { ...opts, timeZone: tz });
const DAY = { month: "short", day: "numeric", year: "numeric" };

export const pacificTime = (iso, lang) => fmt(lang, { hour: "numeric", minute: "2-digit" }).format(new Date(iso));
export const pacificDay = (date, lang) => fmt(lang, DAY).format(date);

export function sourceDate(raw, lang, t) {
  const m = /\d{4}-\d{2}-\d{2}$/.exec(raw);
  if (!m) return raw === "current" ? t("source.current") : raw;
  const d = fmt(lang, DAY, "UTC").format(new Date(`${m[0]}T12:00:00Z`));
  return raw.startsWith("page as saved") ? t("source.saved", { date: d }) : d;
}
