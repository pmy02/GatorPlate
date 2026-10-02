// Pure helpers of the /go code page (docs/UI_SPEC.md A7.1). No DOM; tested with node --test.

// "481 206", "481-206" or "481206" -> "481206"; anything that is not 6 digits -> null.
export function normalizeCode(raw) {
  const digits = String(raw || "").replace(/[\s.-]/g, "");
  return /^\d{6}$/.test(digits) ? digits : null;
}

// Only a card path on this site may be opened (never another site). In fixture mode the static server cannot route
// /c/{token}, so the card page is opened by its folder.
export function cardPath(url, fixtures = false) {
  const m = /^\/c\/([A-Za-z0-9_-]{8,64})$/.exec(String(url || ""));
  if (!m) return null;
  return fixtures ? `/card/?fixtures=1&token=${m[1]}` : m[0];
}
