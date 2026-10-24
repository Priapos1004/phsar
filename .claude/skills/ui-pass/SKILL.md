---
name: ui-pass
description: Walk pages through phone, tablet and desktop widths with the user in the dev-browser — the user finds the issues, Claude sets the width, inspects, proposes and fixes. Use for a responsive pass or any page-by-page visual review.
argument-hint: [page or route to start with]
---

# UI pass

A page-by-page visual review at fixed widths. **The user finds the issues; Claude sets
the viewport, inspects what the user points at, proposes a fix, and makes it once
agreed.** Finding stays with the user on purpose: a solo screenshot audit misses what
they care about.

## Ground rules

- **Discuss before changing.** For each issue: its cause, measured rather than guessed
  and read in the component behind it (which also brings `rules/frontend.md` into
  context), then the options through `AskUserQuestion` — recommendation first, an ASCII preview
  for anything layout. Change nothing until the user picks; a concrete instruction from
  them counts as the pick.
- **Don't navigate.** Set the width with `browser_resize` and inspect the state that is
  open (`browser_snapshot`, `browser_evaluate`, `browser_take_screenshot`). The user
  clicks through pages, overlays and states. Navigate only to log in.
- **The dev servers are the user's.** Never start or stop them.
- **After a fix, re-check the widths already done** (which fixes stay at one width:
  `rules/frontend.md`, "A phone narrows the layout before it shrinks the text"): an
  unprefixed class fixed at 768 changes 375 too.
- After a shared-component fix (`rules/frontend.md`, "Shared components"), **name the
  other pages it reaches**, so the user knows where else to look.
- After a change, hand off as `rules/frontend.md`, "The user verifies UI" describes.
  "Looks good" moves the pass to the next width.

## Setup

- Log in at `/login` with `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `phsar/.env` — the
  admin reaches every page. The guest run uses `GUEST_USERNAME` / `GUEST_PASSWORD`.
- **Height: 700 at phone widths, 900 from 768.** A viewport taller than the user's
  screen pushes the page's bottom off the monitor; it reads as a page that can't scroll
  to its end, or a sheet with no footer.
- Screenshots save only under `.playwright-mcp/` (gitignored); Read one back to see what
  the user sees.
- A console error right after an edit is often the hot reload landing between two edits
  of one change. Re-check once the last edit is in before chasing it.

## Widths

Per page, in this order: **375 → 320 → 768 → 1024 → 1920**.

- **375** first. Tailwind builds up from the phone: unprefixed classes are the phone
  layout and `sm:` / `md:` / `lg:` add on top, so a page settled here stays settled as it
  widens.
- **320**, a quick look for sideways overflow (small Androids, iPhone display zoom). Run
  the overflow scan below.
- **768**, the `sm` / `md` layouts; a `cls.mediaInfoGrid` page (search) is still one
  column.
- **1024**, `lg`: search goes two-column — its narrowest wide layout.
- **1920**: the widest page width (`rules/frontend.md`, "Pages share one width"); past it
  only full-width chrome changes. 1280 (`xl`) is skipped while no `xl:` class exists.

A resized viewport doesn't reproduce a real phone's quirks — iOS input zoom, safe areas,
tap-through. The user checks those on a device at the end.

## What the user wants

The design rules a pass keeps running into are in `rules/frontend.md`: "A phone narrows
the layout before it shrinks the text", "A label's shade follows its surface", "A
toggle's surface decides its component", "Pages share one width" and "Parallel pages
stay parallel".

## Measuring

`browser_evaluate` answers layout questions faster than reading code.

Sideways overflow — what sticks out past the viewport, outside scroll containers:

```js
() => { const w = document.documentElement.clientWidth;
  return [...document.querySelectorAll('body *')].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && (r.right > w + 1 || r.left < -1) && !el.closest('.overflow-hidden, [class*="overflow-x"]');
  }).slice(0, 10).map((el) => [el.tagName, String(el.className).slice(0, 60), el.textContent.trim().slice(0, 30)]); }
```

Whether a string fits — measure it in the element's own font:

```js
() => { const cs = getComputedStyle(document.querySelector('<selector>'));
  const c = document.createElement('canvas').getContext('2d');
  c.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  return Math.round(c.measureText('<text>').width); }
```

Whether a class string wins over another — on a throwaway element: append a parent and
child carrying the classes, read `getComputedStyle`, remove them. Both classes must
already occur in the source, or Tailwind never generated them.

## Cadence

- **Order pages shared-components first**, siblings back to back (the pairs in
  `rules/frontend.md`, "Parallel pages stay parallel"), so later pages arrive partly fixed.
- **Per page**: every width with the user's verdict, then `/ship` and one commit block
  (`workflow.md`, "Commit blocks"); small sibling pages share a block.
- **Track** progress in the version's working roadmap, and decisions plus carry-forwards
  (a fix that should reach a page not yet visited) in its provisional compound doc.
- **Guest run last**, at 375, over the pages where a guest sees something different.
