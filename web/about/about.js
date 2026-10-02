// About page (docs/UI_SPEC.md A7.3): static text. In fixture mode (?fixtures=1) the links to the other pages keep it,
// so a fixture walk-through stays on fixtures. Only working features are visible (docs/UI_SPEC.md A0.6): when the
// server reports the card's other-programs part switched off or outside its table's dates (GET /healthz), the sentence
// about it is hidden.

// true unless the health answer says the programs part is off or not valid today.
export function programsShown(health) {
  const p = health && typeof health === "object" ? health.programs : null;
  if (!p || typeof p !== "object") return true;
  return p.enabled !== false && p.valid_today !== false;
}

function keepFixtures() {
  for (const link of document.querySelectorAll("a[data-keep-fixtures]")) {
    const url = new URL(link.getAttribute("href"), location.origin);
    if (url.pathname === "/talk") url.pathname = "/talk/";
    url.searchParams.set("fixtures", "1");
    link.setAttribute("href", `${url.pathname}${url.search}`);
  }
}

async function checkPrograms() {
  const note = document.getElementById("programs-note");
  if (!note) return;
  try {
    const res = await fetch("/healthz", { headers: { Accept: "application/json" }, cache: "no-store" });
    if (!res.ok) return;
    note.hidden = !programsShown(await res.json());
  } catch { /* keep the static text */ }
}

if (typeof document !== "undefined" && typeof location !== "undefined") {
  if (new URLSearchParams(location.search).get("fixtures") === "1") keepFixtures();
  else checkPrograms();
}
