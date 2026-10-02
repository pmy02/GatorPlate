// Pure helpers of the card's unlocked part (docs/UI_SPEC.md A4.2 row 2b, A6.8): display only.
export const usd = (n) => "$" + Math.round(n).toLocaleString("en-US");

export const countValue = (a, b, t) => (t >= 1 ? b : Math.round(a + (b - a) * (1 - (1 - Math.max(0, t || 0)) ** 3)));

export const widths = (segs, total) => (segs || []).map(([id, v]) => [id, total > 0 ? v / total : 0]);

export function splitAmount(text, amount) {
  const s = amount == null ? "" : usd(amount);
  const i = s && text ? text.indexOf(s) : -1;
  return i < 0 ? null : [text.slice(0, i), s, text.slice(i + s.length)];
}

export const fillCount = (tpl, i, n) => String(tpl).replace("{i}", i).replace("{n}", n);

export const gone = (e) => !!e && (e.status === 404 || e.status === 410);

// The share sheet, else the clipboard, else "field"; "cancelled" when the student closes the sheet.
export async function share(text, nav) {
  try {
    if (nav.share) return await nav.share({ text }), "shared";
  } catch (e) {
    if (e && e.name === "AbortError") return "cancelled";
  }
  try {
    if (nav.clipboard) return await nav.clipboard.writeText(text), "copied";
  } catch { /* the field */ }
  return "field";
}
