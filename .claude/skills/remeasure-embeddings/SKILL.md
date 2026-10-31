---
name: remeasure-embeddings
description: Re-measure every constant calibrated on the search embedding model after a change to what a stored vector is built from — the model, its query/passage prefixes, the case fold, the encode length, or the text `encode_description` joins. Covers the description and notes margins, merge detection's DESC_THRESHOLD, the ranking-test fixtures and the encode cost.
---

# Re-measure after an embedding change

Each constant to re-measure is marked "re-measure on a model change" at its definition;
`grep -rn "re-measure on a model change" phsar/app` lists them. Why they are per-model,
and how prefixes and the boot re-embed work: `docs/features/search.md`. The last run's
tables: the newest compound doc the constants' comments point at.

Run everything on a **restore of a prod backup** — the procedures read real catalogue and
note distributions, which a dev database does not have. The scripts beside this file run
from `phsar/` with `PYTHONPATH=. ../.venv/bin/python <script>`.

## Steps

1. **Export the old vectors first**, before anything re-embeds:
   `desc_threshold.py export <dir>`. Step 5 compares old against new, and the re-embed
   overwrites them.
2. **Make the change and re-embed.** Restart the backend on the new code: the boot probe
   (`embeddings_are_stale`) sees the mismatch and re-embeds the catalogue; wait for the
   "Re-embed complete" log line. If the change is to the encode length or to
   `encode_description`, check the probe really fires — it compares one stored anime. A
   model swap also refits the galaxy map by itself (`docs/features/galaxy.md`); after any
   other change, rebuild it with `POST /admin/galaxy/rebuild` once the re-embed is done.
3. **Description margin** — `margins.py`, first two sections. The rule: the smallest margin
   at which every name and nonsense query admits **≤ 2** semantic-only media. Then read the
   relevant queries' survivors at that margin: they should be on topic (robots for "giant
   robots", Conan for "detective solves murders"). The query sets live in the script; keep
   them stable across runs so the tables compare.
4. **Notes margin** — `margins.py`, notes section, over the admin's own notes. The rule:
   the noise queries admit **nothing**, and the paraphrases find their notes ("calm and
   cozy" → the relaxing ones). Prefer the margin where a generic word ("story") stops
   admitting unrelated notes over one that recovers one more paraphrase. If both
   populations land on the same value, `SEMANTIC_MARGIN` stays one constant; if not,
   split it (`note_cutoff` reads it separately).
5. **`DESC_THRESHOLD`** — `desc_threshold.py compare <dir>`. Pick the threshold that
   flags **no negative** (the curated catalogue's pairs, including the admin's dismissed
   ones) with recall no lower than the old model's at the old threshold. Note the margin
   to the nearest negative.
6. **Ranking fixtures** — run `tests/routers/test_search_ranking.py`,
   `tests/services/test_merge_detection.py` and
   `tests/services/test_vector_embedding_service.py`. The ranking tests assert their
   distances against the cutoff before they search; a failed premise means swapping a
   fixture text for one that holds on the new model, never loosening the assertion. A
   premise must hold on an empty database too: `description_cutoff` averages every stored
   embedding, which on CI is the test's fixtures alone, so compute the cutoff over those
   as well before trusting a local pass. The
   threshold test needs a duplicate pair above and a franchise-sibling pair below the new
   value, with some margin either side.
7. **Encode cost** — time a mean description, the longest one and a short query at the
   VM's thread count (root `CLAUDE.md`, Deployment), against the old model. Update every
   stated per-encode cost (grep the current figure across `docs/` and `phsar/app`) and the
   re-embed duration where they moved; cap the encode length only with a re-run of steps 3–6,
   since the constants hold for the length they were measured at.
8. **Record** the tables in the release's compound doc and point the constants' comments
   at it. Deploy in the daytime: the first boot re-embeds for minutes of poor semantic
   results.
