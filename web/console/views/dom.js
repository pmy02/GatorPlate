// Small DOM helpers for the console views (no framework). CSP-safe: no inline styles or handlers; dynamic values
// go through element.style.setProperty() (docs/UI_SPEC.md A0.10).

const SVG_NS = "http://www.w3.org/2000/svg";
const SPRITE = "/shared/icons.svg";

// h("div", {class: "x", text: "y", attrs: {...}, on: {click}, dataset: {...}, props: {...}}, ...children)
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  apply(el, props);
  append(el, children);
  return el;
}

function apply(el, props) {
  if (!props) return;
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = Array.isArray(v) ? v.filter(Boolean).join(" ") : v;
    else if (k === "text") el.textContent = v;
    else if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === "dataset") for (const [dk, dv] of Object.entries(v)) { if (dv !== undefined && dv !== null) el.dataset[dk] = dv; }
    else if (k === "props") Object.assign(el, v);
    else if (k === "vars") for (const [vk, vv] of Object.entries(v)) el.style.setProperty(vk, vv);
    else if (k === "attrs") {
      for (const [ak, av] of Object.entries(v)) {
        if (av === undefined || av === null || av === false) continue;
        el.setAttribute(ak, av === true ? "" : String(av));
      }
    } else el.setAttribute(k, v === true ? "" : String(v));
  }
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false || c === "") continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

// <svg class="icon" aria-hidden="true" focusable="false"><use href="/shared/icons.svg#i-phone"></use></svg>
export function icon(id, cls = "") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", cls ? `icon ${cls}` : "icon");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `${SPRITE}#${id}`);
  svg.append(use);
  return svg;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function replace(el, ...children) {
  clear(el);
  return append(el, children);
}

// A chip: {text, cls, icon, title}
export function chip(text, { cls = "", iconId = null, title = null, badge = null } = {}) {
  return h("span", { class: ["chip", cls], title }, badge ? h("span", { class: "chip__badge", "aria-hidden": "true", text: badge }) : null,
    iconId ? icon(iconId) : null, h("span", { text }));
}

// Re-render a container while keeping keyboard focus, scroll, anything typed and open <details>: elements are
// matched by data-key. `scope` names what the container shows (the case id): when it changes, nothing typed and no
// scroll position carries over to the other case. A control marked data-server="1" always shows the server's value
// (the status select: a refused change must not stay on screen).
export function rerender(container, build, scope = null) {
  const active = document.activeElement;
  const key = active && container.contains(active) ? active.dataset.key : null;
  const scroller = container.closest("[data-scroll]") || container;
  const same = (container.dataset.scope || "") === String(scope ?? "");
  const top = scroller.scrollTop;
  const typed = new Map();
  const opened = new Map();
  if (same) {
    for (const el of container.querySelectorAll("input[data-key], select[data-key], textarea[data-key]")) {
      if (el.dataset.server) continue;
      if (el.type === "checkbox" ? el.checked !== el.defaultChecked
        : el.tagName === "SELECT" ? [...el.options].some((o) => o.selected !== o.defaultSelected)
          : el.value !== el.defaultValue) typed.set(el.dataset.key, el.type === "checkbox" ? el.checked : el.value);
    }
    for (const el of container.querySelectorAll("details[data-key][data-keep-open]")) opened.set(el.dataset.key, el.open);
  }
  build();
  container.dataset.scope = String(scope ?? "");
  scroller.scrollTop = same ? top : 0;
  for (const [k, v] of typed) {
    const el = container.querySelector(`[data-key="${CSS.escape(k)}"]`);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = v; else el.value = v;
  }
  for (const [k, open] of opened) {
    const el = container.querySelector(`details[data-key="${CSS.escape(k)}"]`);
    if (el) el.open = open;
  }
  if (key && same) {
    const again = container.querySelector(`[data-key="${CSS.escape(key)}"]`);
    if (again) again.focus({ preventScroll: true });
  }
}

export const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// Count a number up inside el (text already formatted by fmt); screen readers get only the final value.
export function countUp(el, to, { from = 0, duration = 450, fmt = String } = {}) {
  if (el._raf) cancelAnimationFrame(el._raf);
  el._raf = null;
  // The final value first: a background tab runs no animation frames, and the amount must never stay blank.
  el.textContent = fmt(to);
  if (reducedMotion() || from === to || (typeof document !== "undefined" && document.hidden)) return;
  const start = performance.now();
  const step = (t) => {
    const p = Math.min(1, (t - start) / duration);
    const eased = 1 - (1 - p) ** 3;
    el.textContent = fmt(Math.round(from + (to - from) * eased));
    if (p < 1) el._raf = requestAnimationFrame(step); else el._raf = null;
  };
  el._raf = requestAnimationFrame(step);
}
