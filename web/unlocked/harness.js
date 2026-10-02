// Fixture-only harness for the card's unlocked part (docs/UI_SPEC.md A9 item 16): mounts the widget with the card
// fixture of web/fixtures (card_maria_{en,es}.json) the way the card page does, and replays the W4 answers and the
// "I applied" reply through web/fixtures/index.json. It never runs outside fixture mode.
import { FIXTURES, fetchJSON } from "/shared/api.js";

const STRINGS = {
  en: { retry: "Try again", badlink: "This card link doesn't work. It may have expired or been deleted." },
  es: { retry: "Intentar otra vez", badlink: "Este enlace no funciona. Puede que haya vencido o que se haya borrado." },
};
const query = new URLSearchParams(location.search);
const token = /^[\w-]{1,64}$/.test(query.get("token") || "") ? query.get("token") : "fixture";
let lang = query.get("lang") === "es" ? "es" : "en";
let mounted = false;
const el = document.getElementById("unlocked");
const note = document.getElementById("note");
const seg = document.querySelector(".seg");

async function load() {
  const card = await fetchJSON(`/api/card/${token}?lang=${lang}`, { lang });
  document.documentElement.lang = lang;
  for (const b of seg.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.lang === lang));
  if (mounted) {
    window.GPUnlocked.render(card.unlocked);
    return;
  }
  mounted = true;
  window.GPUnlocked.mount(el, card.unlocked, {
    token, lang, t: (key) => STRINGS[lang][key] || key,
    onGone: () => { el.hidden = true; note.hidden = false; note.textContent = STRINGS[lang].badlink; },
  });
}

if (FIXTURES) {
  note.hidden = true;
  seg.hidden = false;
  seg.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-lang]");
    if (b && b.dataset.lang !== lang) {
      lang = b.dataset.lang;
      load();
    }
  });
  load().catch(() => { note.hidden = false; note.textContent = "The card fixture could not be loaded."; });
}
