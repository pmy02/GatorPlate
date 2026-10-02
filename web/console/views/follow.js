// The live transcript "sticks to the bottom unless the user scrolled up" (docs/UI_SPEC.md A3.8). The intent comes
// from the reader's own scroll events, never from the box's size at the moment new lines arrive: a layout change in
// the middle of a call (Presenter on or off, a window resize) grows the content without a scroll event, and must not
// turn following off. No imports and no DOM globals, so node --test can drive it with a stand-in box.

export const STICK_PX = 48; // closer than this to the bottom counts as "at the bottom"

export function followBottom(box, { slack = STICK_PX } = {}) {
  let stick = true;
  const gap = () => box.scrollHeight - box.scrollTop - box.clientHeight;
  // Scroll events arrive after the scroll; reading the geometry then keeps our own pins sticky as well.
  box.addEventListener("scroll", () => { stick = gap() < slack; }, { passive: true });

  function pin() {
    if (stick) box.scrollTop = box.scrollHeight;
    return stick;
  }

  // A resize of the box itself (window size, Presenter) re-pins without waiting for the next line.
  let observer = null;
  const RO = globalThis.ResizeObserver;
  if (typeof RO === "function") {
    observer = new RO(() => { pin(); });
    observer.observe(box);
  }

  return {
    pin,
    sticking: () => stick,
    stop() { if (observer) observer.disconnect(); observer = null; },
  };
}
