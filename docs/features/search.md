# Search

Title, description and note search over the catalogue, filtered, at two grains:
**media** (one entry) and **anime** (a franchise, aggregated from its media).

**Code**: `services/vector_embedding_service.py` (embeddings) →
`services/media_search_service.py` / `services/anime_search_service.py` (queries) →
`daos/search_filters.py` (shared filter/order helpers) →
`services/filter_service.py` (facet values).

## Embeddings

Model is `paraphrase-multilingual-MiniLM-L12-v2`, stored in pgvector. Searches read
the `description` and `rating_notes` embeddings. Title embeddings are still written
beside the description ones, but nothing reads them: title search matches literally
(below).

**Everything is case-folded before encoding.** The model is *cased*, so the same
text in different capitalisation produces materially different vectors — enough
that capitalising a query reorders the results and can bury the intended show.
`_fold` is the single chokepoint every embedding passes through, queries and
stored documents alike — `generate_query_embedding` and `generate_embedding` are
siblings over `_run_encode`, not one calling the other — so folding there keeps
both in one case space.

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

## Title search

**A title query is a filter, not a ranking.** A row matches when one of its title
variants — romaji, English, Japanese, or a synonym (`other_names`) — contains the
query or fuzzy-matches it; everything else is left out. At the anime grain the
variants are the anime's own plus every one of its media's, so a side story's title
finds the franchise. `title_match_score` is the one definition the anime, media and
`/search/ratings` searches share.

A **substring** hit (`ilike`) outranks any fuzzy hit. The **fuzzy** tier must stay
pg_trgm `word_similarity` and not plain `similarity`, which penalises the length
mismatch between a short query and a long title and buries the partial match. It tries
`TITLE_MATCH_THRESHOLDS` strictest first, moving on only when the stricter matches
nothing; their calibration sits beside them.

**The anime grain matches in HAVING**, as `GREATEST(anime variants, MAX(media
variants))` after grouping — a title query is a filter, so the
[Anime-view filters](#anime-view-filters) invariant binds it. Pinned by
`test_media_title_reaches_its_anime`.

## Description search

**Literal hits first, semantic neighbours after, down to a cutoff.** A media is a
literal hit when every query word starts a word of its titles or description — the
text its description embedding encodes, so both tiers judge the same media. A word
*start* (`\m`): a prefix, never an infix. Each tier is ordered nearest first;
`description_passes` is the one ranker every description search shares.

**The cutoff is relative to the query**: a semantic hit must sit `SEMANTIC_MARGIN`
below the catalogue's mean distance to that query. A fixed distance cannot serve both
ends — a short name sits close to every description, a sentence far from all of
them. The mean runs over the whole catalogue, unfiltered, so no filter moves it and
`/search/ratings` measures against the catalogue, not the caller's own ratings. A
media with an empty description is never a semantic hit: its vector encodes the title
alone, and such vectors sit near every short query. The margin is calibrated for the
embedding model, beside its constant.

**When nothing matches at all, it retries once, typo-tolerant**: every word
`word_similarity`-matched at the strict title threshold. That reaches a typo at the
end of a word, not a swap mid-word.

**The anime grain decides in HAVING**, for the title match's reason: a literal hit on
any media makes the anime one, and the semantic test averages its media's distances —
an aggregate that must ignore group size, since `SUM` would rank a franchise worse for
having more entries. Pinned by `test_description_literal_hit_on_a_side_story_reaches_its_anime`.

Rating-note search ranks by note-embedding distance alone: no literal tier, no cutoff.

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
`weighted_mean_score_expr` / `weighted_mean_votes_expr` used by every anime-grain
ordering by score, the score HAVING filters, and `score_top_percent`. Keeping them in step is what stops
the displayed number, the ranking and the "Top N%" pill from drifting apart.

`total_episodes`, `total_watch_time`, `media_count` and genre majority stay over
**all** media.

## Sorting

**A query decides which rows match; the sort decides their order.** Title and
description queries keep their match set (every pass's restriction, the
strict-then-loose retry), and `sort` only replaces the ORDER BY. `relevance`, the
default, is the query's own match order, and top rated without a query. `limit` runs 1–1000,
default 50.

`sort_order` is the one implementation at both grains, and its docstring gives the
tiebreak. At the anime grain, the keys built on score or votes read the aggregates its
card shows ([main story only](#anime-score-is-main-story-only)); the rest, apart from
release, read the anime's own row.

**Release is one timeline.** An anime sits at its next announced season, else at
`TBA_SEASON_KEY` if it has an announcement without a season, else at its latest aired
season, all read from its main-story media (`MAIN_STORY_RELATIONS`) alone: a recap or
OVA neither announces a franchise nor makes it fresh. A media sits at its own
season, side stories included, or at TBA while announced without one. TBA
follows every real season, so ascending runs oldest → announced → TBA, and descending
the reverse. A row with no season comes last either way. A media still "Not yet aired"
after its season has passed sorts at that past season.

**Title sorts in the user's name language**, through `display_title`. **Random is
daily**: md5 of the row's uuid and the UTC date, so every viewer gets the same order
that day.

## The caller's own ratings

Media-view results carry `is_rated` (`MediaSearchResult`), so a hit can show that
the caller already rated it. It is filled after the search query, from one indexed
lookup over the page of hits — bounded by the result limit, and deliberately not
threaded into `daos/search_filters.py`, which knows nothing about a user and must
keep it that way: the anime query's GROUP BY and the "a filter never rescopes the
aggregates" invariant both depend on that.

The anime grain has no equivalent field. Its counterpart is the per-anime coverage
tier from `/ratings/coverage`, which the client indexes by anime uuid — see
[ratings.md](ratings.md).

## Ordering media within an anime

`filter_service.chronological_media_key(season_year, season_name, mal_id)` is the
project-wide sort key. The backend spoiler-frontier walk, the anime-detail media
table and timeline, and the related-media carousel all call it, so the order in
the carousel matches the table matches what the frontier walks. Diverging keys
would be a silent UX bug.

The client-side frontier walk is the one sanctioned divergence — see
[spoilers.md](spoilers.md).

---

**Why it is this way**
- [Anime score over the main story](../../compound-docs/2026-07-19-anime-score-main-only.md) — the prod-data study behind the weights
- [Further QoL](../../compound-docs/2026-06-22-v0.14.11-further-qol.md) — `score_top_percent` query shape
- [Quality-of-life upgrades](../../compound-docs/2026-07-27-v0.15.3-quality-of-life.md) — filters no longer rescoping the score
- [Efficiency improvements](../../compound-docs/2026-08-06-v0.15.4-efficiency-improvements.md) — the aggregate-in-ORDER-BY change and query memoization
- [Search rework](../../compound-docs/2026-10-07-v0.16.0-search-rework.md) — the title-match and description-cutoff studies, the embedding-model comparison, and their problem cases
