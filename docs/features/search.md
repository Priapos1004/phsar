# Search

Title, description and note search over the catalogue, filtered, at two grains:
**media** (one entry) and **anime** (a franchise, aggregated from its media).

**Code**: `services/vector_embedding_service.py` (embeddings) →
`services/media_search_service.py` / `services/anime_search_service.py` (queries) →
`daos/search_filters.py` (shared filter/order helpers; the notes passes in `daos/rating_dao.py`) →
`services/filter_service.py` (facet values).

## Embeddings

Model is `paraphrase-multilingual-MiniLM-L12-v2`, stored in pgvector. Searches read
the `description` and `rating_notes` embeddings. A description embedding encodes the
row's titles together with its description, so a title change regenerates it. Titles
have no embedding of their own: title search matches literally (below). Changing the
model re-tunes every constant calibrated on it, each marked "re-measure on a model
change".

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
finds the franchise. `title_match_score` is the one definition every title search shares.

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
`match_passes` is the one ranker every literal-first search shares ([notes](#notes-search) too).

**The cutoff is relative to the query**: a semantic hit must sit `SEMANTIC_MARGIN`
below the catalogue's mean distance to that query. A fixed distance cannot serve both
ends — a short name sits close to every description, a sentence far from all of
them. The mean runs over the whole catalogue, unfiltered, so no filter moves it. A
media with an empty description is never a semantic hit: its vector encodes the title
alone, and such vectors sit near every short query.

**When nothing matches at all, it retries once, typo-tolerant**: every word
`word_similarity`-matched at the strict title threshold. That reaches a typo at the
end of a word, not a swap mid-word.

**Both retries count what the filters leave**: a filter that excludes every strict
match lets the looser matches through.

**The anime grain decides in HAVING**, for the title match's reason: a literal hit on
any media makes the anime one, and the semantic test averages its media's distances —
an aggregate that must ignore group size, since `SUM` would rank a franchise worse for
having more entries. Pinned by `test_description_literal_hit_on_a_side_story_reaches_its_anime`.

## Notes search

**The description tiers over the caller's own notes.** A literal hit is a note holding
every query word as a word start — the note is all its embedding encodes — and semantic
hits follow down to `SEMANTIC_MARGIN` below the mean distance over **the caller's own
notes**, the population searched. Notes are short, so their mean sits nearer a query
than the catalogue's does, which would admit dozens of loose matches. With only a few
notes the mean sits near each one's own distance, so the semantic tier all but closes and
the search is literal. The typo retry runs as for descriptions.

**The anime grain takes its nearest note** (MIN), not description's average: an anime's
notes are about different entries, so an unrelated second note must not sink the one
that matches. An anime matches exactly when one of its media does at the media grain.
Decided in HAVING, for the title match's reason. Pinned by
`test_notes_anime_grain_matches_on_its_nearest_note`.

**Each hit quotes the note that matched** (`matched_note`), filled after the query over
the page of hits: a media its own note, an anime the best of its media's
(`rating_dao.best_note_by_anime_id`).

## Anime-view filters

**A filter selects which anime; it never rescopes the aggregates.**
`apply_anime_pre_filters` emits `Anime.id IN (SELECT media.anime_id WHERE …)` — one
subquery, so the studios count only on media the other conditions match ("studio X +
type TV" means one media is a TV by X) — rather than filtering the grouped rows.

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

**Genre majority is a separate condition.** A selected genre counts for an anime
when a majority of its media carry it (`count * 2 > total`, the same threshold that
populates the dropdown). It stays **one non-correlated pass** — per-(anime, genre)
counts and per-anime totals computed once, joined, survivors counted against the
number the mode needs. A correlated majority-subquery per genre is superlinear:
each one adds a SubPlan *and* widens the set every existing SubPlan re-evaluates
over, and this fires on every genre chip toggle. The denominator is the anime's
**full** media count, so a stacked studio filter can't shrink it.

**Any or all.** `genre_mode` (default all) and `studio_mode` (default any) choose
whether a row needs one selected value or every one. An anime's genres are the ones
reaching their majority; its studios are the union over the media the categorical
filters match, coupled as above. The media grain tests the media itself.

**Top N% is the badge.** Both badges and the `top_percent` filter read one ranking,
`top_percent_ranking`, so N keeps exactly the rows whose badge reads N% or better;
its docstring gives the population and the rounding.

**`upcoming_main` reads the main story** (`upcoming_main_media`), as the [release
sort](#sorting) does. It departs from
the card's `has_upcoming`, which counts any announced media, so that "upcoming +
release ascending" lists the next seasons — an anime announcing only an OVA would
sort at its last aired season.

## Anime score is main-story only

`avg_score` / `avg_scored_by` are relation-weighted means over
`RELATION_SCORE_WEIGHTS` — Main and AlternativeVersion count 1, SideStory and
Summary count 0 — i.e. the same anchor set the spoiler frontier uses.

The Python computation in `_compute_anime_aggregates` is the twin of the SQL
`weighted_mean_score_expr` / `weighted_mean_votes_expr`, which every anime-grain
query reads the score through. Keeping them in step is what stops
the displayed number, the ranking and the "Top N%" pill from drifting apart.

`total_episodes`, `total_watch_time`, `media_count` and genre majority stay over
**all** media.

## Sorting

**A query decides which rows match; the sort decides their order.** Every query
keeps its match set (every pass's restriction, the
strict-then-loose retry), and `sort` only replaces the ORDER BY. `relevance`, the
default, is the query's own match order, and top rated in its default direction without a
query, whatever `sort_dir` says. `limit` runs 1–1000,
default 50.

`sort_order` is the one implementation at both grains, and its docstring gives the
tiebreak. At the anime grain, the keys built on score or votes read the aggregates its
card shows ([main story only](#anime-score-is-main-story-only)); a key computed over
the anime's media says so below; the rest read the anime's own row.

**Release is one timeline.** An anime sits at its next announced season, else at
`TBA_SEASON_KEY` if it has an announcement without a season, else at its latest aired
season, all read from its main-story media (`MAIN_STORY_RELATIONS`) alone: a recap or
OVA neither announces a franchise nor makes it fresh. A media sits at its own
season, side stories included, or at TBA while announced without one. TBA
follows every real season, so ascending runs oldest → announced → TBA, and descending
the reverse. A row with no season comes last either way. A media still "Not yet aired"
after its season has passed sorts at that past season.

**Latest aired says how fresh; release says what comes next.** An anime sits at its main
story's last finished season, else its airing one, else its closest announced season,
else TBA — so announcements count only for an anime with nothing aired, and one with a
finished season and another airing sits at the finished one. A media sits at its own
season, as for release. Release stays beside it: holding a continuation at its last
finished season, latest aired can't give [`upcoming_main`](#anime-view-filters) its
soonest-first order. Latest aired descends by default.

**Title sorts in the user's name language**, through `display_title`. **Random is
daily**: md5 of the row's uuid and the UTC date, so every viewer gets the same order
that day. **Your rating** is the mean of the caller's ratings over the anime's rated
media, whatever their status — the `/ratings` page's mean — or the media's own rating;
unrated rows come last.

## Personal filters and sort

**Every input scoped to the caller reads the caller's own data, and
`daos/search_filters.py` still knows nothing about a user** — the anime query's GROUP BY
and the [Anime-view filters](#anime-view-filters) invariant depend on that. The service
resolves the personal filters to ids (`filter_service.personal_scope`) and the DAOs select rows
by them, `IN` / `NOT IN` on the primary key, so the grouped media and every aggregate stay
whole. `your_rating` reaches `sort_order` as a key the DAO builds over its own outer join
onto the caller's ratings, and notes search matches over the same join
(`rating_dao.note_passes`). Pinned by `test_personal_filters_and_sort_do_not_rescope_the_aggregates`.

- **States are a union.** The anime grain takes the [rated states](ratings.md#rated-state-and-coverage);
  the media grain its own rating's watch status, or `none`. A state of the other grain is
  a 400.
- **An anime is watchlisted when any of its media is**, as its bookmark shows.
- **They narrow the spoiler scope, never replace it**: in hide mode the media grain
  starts from the visible set.
- **A guest gets 403** for any of them, `watchlisted=false` and the notes mode without a
  query included: a read scoped to the caller (`rules/backend.md`, Roles).

Media-view results also carry `is_rated` (`MediaSearchResult`), filled after the query
from one indexed lookup over the page of hits. The anime grain's counterpart is the
coverage tier from `/ratings/coverage`, which the client indexes by anime uuid.

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
- [Further QoL](../../compound-docs/2026-06-22-v0.14.11-further-qol.md) — the badge's rank-based rounding
- [Quality-of-life upgrades](../../compound-docs/2026-07-27-v0.15.3-quality-of-life.md) — filters no longer rescoping the score
- [Efficiency improvements](../../compound-docs/2026-08-06-v0.15.4-efficiency-improvements.md) — the aggregate-in-ORDER-BY change and query memoization
- [Search rework](../../compound-docs/2026-10-07-v0.16.0-search-rework.md) — the studies and problem cases behind the v0.16.0 search changes
- [Search UI](../../compound-docs/2026-10-09-v0.16.1-search-ui.md) — the notes cutoff study and why the anime grain takes the nearest note
