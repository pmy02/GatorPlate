// Tiny string lookup for page chrome (each page owns its tables; content strings come from the API).
// t(key, vars) fills {placeholders}; a missing key falls back to English, then to the key itself.

export function pageLang() {
  const q = new URLSearchParams(location.search).get("lang");
  if (q === "en" || q === "es") return q;
  return (navigator.language || "").toLowerCase().startsWith("es") ? "es" : "en";
}

export function fill(template, vars = {}) {
  return String(template).replace(/\{([a-z_][a-z0-9_]*)\}/gi, (m, k) => (k in vars ? String(vars[k]) : m));
}

export function createT(tables, getLang = pageLang) {
  return function t(key, vars) {
    const lang = typeof getLang === "function" ? getLang() : getLang;
    const s = (tables[lang] && tables[lang][key]) ?? (tables.en && tables.en[key]) ?? key;
    return fill(s, vars);
  };
}
