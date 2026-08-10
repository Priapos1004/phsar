# Search

Semantic + filtered search over the catalogue, at two grains: **media** (one entry)
and **anime** (a franchise, aggregated from its media).

**Code**: `services/vector_embedding_service.py` (embeddings) →
`services/media_search_service.py` / `services/anime_search_service.py` (queries) →
`daos/search_filters.py` (shared filter/order helpers) →
`services/filter_service.py` (facet values).

## Embeddings

Model is `paraphrase-multilingual-MiniLM-L12-v2`, stored in pgvector. Three
targets, selected by `SearchType`: `title`, `description`, `rating_notes`.

**Everything is case-folded before encoding.** The model is *cased*, so the same
text in different capitalisation produces materially different vectors — enough
that capitalising a query reorders title results and can bury the intended show.
`generate_embedding` is the single chokepoint every embedding passes through,
queries and stored documents alike, so folding there keeps both in one case space.
The SQL literal-match bonuses still use the raw query, which is already
case-insensitive.

**Queries are memoized; document text is not.** `generate_query_embedding` wraps a
256-entry LRU over the folded text (~30 ms per encode, ~0.1 ms on a hit, ~4 MB at
capacity); `generate_embedding` stays uncached.

The split is the design, not a tuning detail: the two populations have opposite
reuse profiles. Queries repeat; a document string is encoded once and never again,
so a sweep or a full re-embed inserts thousands of keys that can never be hit. One
shared cache would therefore be fully evicted after every nightly sweep —
cold exactly when the query cache was measured to matter.

`_encode` returns a **tuple**, copied into a fresh list per call: the memoized
value is shared by every caller of a key and callers assign it straight onto ORM
attributes, so returning the cached object would hand out a shared mutable with no
owner. Pinned by `test_cache_hits_do_not_alias_the_returned_list`; the shared fold
that keeps queries and documents in one case space is pinned by
`test_query_and_document_paths_produce_the_same_vector`.

## Ranking

`apply_vector_ordering` subtracts a two-tier bonus from `cosine_distance` so
literal matches outrank merely thematically-similar shows: a flat bonus for a
substring (`ilike`) match, and a pg_trgm `similarity()` bonus scaled linearly above
a threshold so typos still surface the intended title.

Description and rating-note search skip both bonuses — those are semantic queries,
not literal ones.

**Anime-level ranking aggregates the distance in the ORDER BY** rather than putting
the embedding in the GROUP BY. Three constraints shape that:

- it must wrap the **distance**, since pgvector has no `min(vector)`;
- it must **ignore group size** — the query groups over joined media rows, so a
  six-media anime contributes six identical rows. `min`/`avg` qualify; `sum` would
  rank a franchise six times worse for being a franchise;
- the literal-match bonuses stay un-aggregated, being functionally dependent on the
  grouped primary key.

Grouping by the vector instead would put 384 floats in the hash/sort key of every
input row, forcing a GroupAggregate plus a full sort where a HashAggregate would do
— and Postgres won't infer functional dependency for a column on a different table.

## Anime-view filters

**A filter selects which anime; it never rescopes the aggregates.**
`apply_anime_pre_filters` emits `Anime.id IN (SELECT media.anime_id WHERE …)` — one
subquery, so all conditions hold for the *same* media row ("studio X + type TV"
means one media is a TV by X) — rather than filtering the grouped rows.

Those grouped rows also feed `avg_score`, `avg_scored_by`, `total_episodes`,
`media_count` and every HAVING filter. Narrowing them would make the displayed
score depend on which media the filter kept: an anime credited to a studio only
through a side story (relation weight 0) would rank on an empty main set while its
card shows the mean over all its main media. The invariant is that the shown score
and the ordering derived from it are filter-independent — pinned by
`test_studio_filter_does_not_rescope_score_or_ordering`. The card refetches
unfiltered, so only the SQL side could ever drift.

Some filters must mirror the card's own derivation rather than testing per-media:
`age_rating` filters against `MAX(age_rating_numeric)`, `airing_status` against the
priority-collapsed value (Currently → Finished → Not yet aired). Otherwise an anime
with one finished side story surfaces under "Finished" while its card reads
"Currently Airing".

**Genre majority is a separate condition.** Every selected genre must be carried by
a majority of the anime's media (`count * 2 > total`, the same threshold that
populates the dropdown). It stays **one non-correlated pass** — per-(anime, genre)
counts and per-anime totals computed once, joined, survivors counted against the
number of genres selected. A correlated majority-subquery per genre is superlinear:
each one adds a SubPlan *and* widens the set every existing SubPlan re-evaluates
over, and this fires on every genre chip toggle. The denominator is the anime's
**full** media count, so a stacked studio filter can't shrink it.

## Anime score is main-story only

`avg_score` / `avg_scored_by` are relation-weighted means over
`RELATION_SCORE_WEIGHTS` — Main and AlternativeVersion count 1, SideStory and
Summary count 0 — i.e. the same anchor set the spoiler frontier uses.

The Python computation in `_compute_anime_aggregates` is the twin of the SQL
`weighted_mean_score_expr` / `_votes_expr` used by the default ordering, the
score HAVING filters, and `score_top_percent`. Keeping them in step is what stops
the displayed number, the ranking and the "Top N%" pill from drifting apart.

`total_episodes`, `total_watch_time`, `media_count` and genre majority stay over
**all** media.

## Ordering media within an anime

`filter_service.chronological_media_key(season_year, season_name, mal_id)` is the
project-wide sort key. The spoiler frontier walk, the anime-detail media table and
timeline, and the related-media carousel all call it, so the order in the carousel
matches the table matches what the frontier walks. Diverging keys would be a silent
UX bug.

---

**Why it is this way**
- [Anime score over the main story](../../compound-docs/2026-07-19-anime-score-main-only.md) — the prod-data study behind the weights
- [Further QoL](../../compound-docs/2026-06-22-v0.14.11-further-qol.md) — `score_top_percent` query shape
- [Quality-of-life upgrades](../../compound-docs/2026-07-27-v0.15.3-quality-of-life.md) — filters no longer rescoping the score
- [Efficiency improvements](../../compound-docs/2026-08-06-v0.15.4-efficiency-improvements.md) — the aggregate-in-ORDER-BY change and query memoization
