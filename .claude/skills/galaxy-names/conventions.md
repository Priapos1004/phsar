# Galaxy naming conventions

What a sector or region name must do. A reviewer reads this whole. Why the first names
were chosen, with the alternatives that lost, is in
[compound-docs/2026-11-07-galaxy-names.md](../../../compound-docs/2026-11-07-galaxy-names.md).

## It works as a map label

- **About 25 characters.** Labels wrap at the widths in `nameStyle` (`GalaxyMap.svelte`).
- **A region name reads on its own**, since it replaces its sector's when zoomed in
  ([USER_FLOWS §3d](../../../phsar/frontend/USER_FLOWS.md#3d-galaxy)): "Mecha & Space",
  not "Space".
- **A region repeats its sector's defining word, last** — "Modern Battle Shounen",
  "Romance Donghua" — wherever the sector has one (a demographic, "Donghua"), unless the
  name reads better without it ("Shy Crushes & Teasing"). Last, because some names have
  no good first-word form ("Modern Battle Shounen").

## It says what the group holds

- **Content over judgement.** Score and era words only where the fit split the sector on
  them (Modern / Classic Battle Shounen). "Acclaimed" and "low-rated" otherwise go.
- **Plain words over genre jargon**, and the friendlier phrasing when two are equally
  true. "Donghua" is the map's word for Chinese animation; no nationality words.
- **No over-claiming.** Check a name's claim against the members: a "Heroines…" name needs
  most leads to be female, and "Overpowered" doesn't fit a group holding Ascendance of a
  Bookworm. A group of two clusters names both halves ("Supernatural & Dark Shounen"); a
  group with no common thread takes the best umbrella and is marked ⚠ in `names.md`.
- **Reuse a dropped name** when the group holds its old anchors — the rebuild lists where
  each dropped name's members went.

## It fits the map as a whole

- **Sibling sectors read as sets** (Shounen Manga / Seinen Manga).
- **No near-twins anywhere on the map**, across sectors too. A shared generic word is fine
  ("Battles", "Fantasy", "Romance"); the same two-word phrase, or a third name ending in
  the same distinctive word ("… Thrillers"), is not.
- **Spellings:** "Rom-Coms" (and "Rom-Com" as a modifier); "Anime" never in a name.
