# Galaxy map

A fitted 2-D map of every anime: one star each, grouped into named **sectors** that
split into **regions**. There is one live fit at a time, and a refit replaces it whole.

**Code**: `services/galaxy_compute.py` (the numerics, run in a child process) →
`services/galaxy_dispatcher.py` (the `galaxy_rebuild` job) → `services/galaxy_service.py`
(serving, placing, enqueueing, `ensure_map`, hand names) → `daos/galaxy_dao.py` →
`models/galaxy.py`. The map's endpoints are in `routers/browse.py`, the admin ones in
`routers/admin_galaxy.py`. The tab is `GalaxyTab.svelte` over `GalaxyMap.svelte`, with
`utils/galaxy.ts` and `stores/galaxyView.ts`.

## What a star is made of

A star's feature vector joins blocks read off the anime and its media:

- **synopsis**: the stored `anime_search` description embedding ([search](search.md#embeddings));
- **tags**: genres and themes as one list, as the app shows them, each tag held by the share
  of the anime's media carrying it (the majority rule's measure) and counted by its rarity,
  the measure the neighbour badges rank by. The list counts by how much it says
  (`_evidence`, `TAG_PSEUDO`), so a theme left untagged only shortens the list;
- **demographics**: the share of the anime's media carrying each. A block of its own,
  because lacking one says something: a demographic follows the source magazine, which a
  light novel or an original has none of;
- **source and format**: shares over the main story, with log watch hours added to format;
- **age and era**: the highest age tier and the first main-story year;
- **studios**: the most productive studios one-hot, and every other studio as a big, mid
  or small output bucket;
- **quality**: the anime's MAL score and log vote count, as the app shows them.

Each block is balanced against the others over the training set and then weighted
(`WEIGHTS`). A value known only partly counts toward the training anime's mean, and the
rest of its spread becomes uncertainty (`_blocks`), so two anime lacking the same thing are
no likelier alike than any two: a synopsis by its length (`SYNOPSIS_HALF`; the embedding
[reads the titles too](search.md#embeddings)), every other value when it is missing. The tag
list weighs its own evidence, and demographics take none (above). The vector is stored on
the star (`features`), beside its `uncertainty`.

**Only settled anime shape the map.** An anime trains the fit when its main story has a
finished media with a MAL score. Every other anime (airing, announced, or finished but
unscored) is placed onto the fitted map instead, with `trained` false. Letting them train
behind a has-score flag builds a mixed "unrated island" and destabilises the sectors
around it.

### Distance

Stars compare by `galaxy_compute.distances`: the squared distance between their vectors
plus each star's uncertainty. Uncertainty is what a vector cannot carry — what `_evidence`
leaves of a tag list, and the spread of every value known only partly — so an anime the catalogue
says less about sits farther from every other, rather than alike to the others like it. No
vector space holds it, so UMAP reads the distances precomputed. Everything that compares two
stars uses this sum; `GalaxyDAO.nearest` repeats it in SQL, where the function cannot run.
A plain distance between `features` alone would make two anime alike on what neither
carries.

## The fit

1. UMAP reduces the trained stars to 10-D, from their [distances](#distance).
2. **Sectors** come from HDBSCAN on the 10-D, size-capped (`MAX_SECTOR_FRACTION` says
   why). A star HDBSCAN calls noise takes the sector most of its nearest labelled stars
   are in (`NOISE_VOTERS` says why). A star is `between` when HDBSCAN's outlier score
   finds it among the least at home in its sector (`BETWEEN_SHARE` says why).
3. **Regions** come from Ward clustering inside each sector, about one region per
   `REGION_SIZE` stars. Ward runs on the 10-D plus MAL score and era, so a sector splits
   by quality and age as well as by content.
4. A second UMAP, fitted on the 10-D, gives the 2-D layout the map draws.

Untrained anime go through the fitted models, one at a time — UMAP's transform otherwise
places a batch's anime by what else is in it:

- both UMAP `transform`s, the 10-D one from a newcomer's distances to the training anime,
  which the pickle keeps;
- HDBSCAN's `approximate_predict`, its neighbours' sector when it answers noise, and
  `between` past the fit's outlier-score line;
- the nearest region centroid in the sector's region space.

`galaxy_compute.place` does the same from the pickled models alone, for anime the map has
not seen yet.

**A refit starts from the live map.** Both UMAPs start from the stars' stored coordinates,
a newcomer beside its nearest known stars. As a result the median star moves a few percent
of the map instead of the whole map reshuffling. Not after the vectors change — a model
swap, a new `vectors_key`, or the boot re-embedding the stored synopsis vectors
(`galaxy_service.same_vectors`, `vectors_reembedded`): that layout means nothing to the new
vectors, so the refit starts cold. A library bump or a change to the fitting alone keeps the
warm start.

Sectors still churn between fits, which is why names follow members rather than numbers.
The job reports the movement as `median_movement`.

## The rebuild job

`galaxy_rebuild`:

1. loads the catalogue, the live map's coordinates (when its vectors still match) and its
   hand names;
2. commits, so no transaction stays open across the fit;
3. runs the fit in a spawned child (`galaxy_service.run_in_child` says why);
4. swaps the old fit for the new one in a single transaction (`replace_fit`).

A failed fit writes nothing and leaves the live map in place. The job has no maintenance
bracket, because it writes only its own tables.

### When the map is rebuilt

An admin can rebuild on demand with `POST /admin/galaxy/rebuild`, confirmed by typing their
username, because the new fit replaces the live map whole; the job shows in their bell.
Otherwise `galaxy_service.ensure_map` decides. It is asked at every boot, behind the
re-embed (`main.py` says why), and by every `schedule-nightly`. It enqueues a rebuild
when the map is due:

- **there is no map**: a first deploy or a fresh database;
- **the map was built from something that has changed**: each fit records what it depends
  on besides the catalogue (`built_from`), so a change to any of it — a model swap, a
  change to the vectors (`vectors_key`) or to the fitting (`FITTING`), a library bump —
  refits by itself;
- **the map predates this quarter's refit date**: the 15th of Jan/Apr/Jul/Oct, two weeks
  after a season ends, so that season's finished shows have settled scores and join the
  training set.

It enqueues nothing while a rebuild is already queued or running, or while the catalogue
is too small to cluster (`MIN_CATALOGUE`). Because the cron asks every night, a missed
night catches up on the next.

## Placing new anime

Between fits, an anime with no star (scraped since the fit, or split off another) is placed
onto the live map through its fitted models, leaving every other star where it is.
`galaxy_service.place_unplaced` places them all in one child, at the end of each update
sweep and at boot. A seasonal sweep's anime arrive through the scrapes it enqueues
([jobs](jobs.md#season-sweeps)), so they land at the next night's update sweep. A map on
its way out — one a queued or running rebuild will replace, or one whose `built_from` no
longer matches — takes no new stars (`place_unplaced` says why). A failed placement
delays the night's new stars to the next sweep or boot, and never fails the sweep.

## Serving the map

`GET /browse/galaxy` serves the live map whole (`GalaxyMapOut`): every sector and region,
and every star with what a hover card shows of its anime, its "Top N%" among them — the
search's `top_percent_ranking`, so the map and the Top rated sort rank alike. It is the
same for every viewer, guests included, and empty until the first fit lands.

`GET /browse/galaxy/{anime_uuid}/neighbours` answers the `NEIGHBOURS` stars nearest by
[distance](#distance), nearest first, each with what it shares with the one asked about
(`GalaxyNeighbourOut`). Every shared trait is weighed on one scale, the chance two anime
on the map share it anyway, so a rare genre outranks a merely close synopsis: for every trait
but the synopsis the share of stars carrying it (`GalaxyDAO.trait_counts`), for the synopsis
the share of random pairs this alike (the `pair_cosine_percentiles` each fit records, over
anime that have one — an anime without a synopsis shares none). A neighbour lists the rarest
`SHARED_SHOWN`, none above `SHARED_CHANCE_MAX` (the constants say why). It is asked on demand rather than inlined in the map, so a star placed
since the map loaded has neighbours too.

## The tab

The map is drawn in the browser from that one payload, its sector colours included
(`sectorHues`); the MAL score colouring ranks by Top N%. Find an anime is the search's own
title match (`/search/anime`), kept to anime with a star. The filters ask
`/search/anime/uuids` which anime they keep, and the tab lights those.

## Names

Every group gets an **auto name** on every fit, so a fresh database needs nothing seeded.
The name lists the group's distinguishing values against a reference population: the
catalogue for a sector, the parent sector for a region. Both are measured over the training
anime alone, so the anime placed onto a group — the least known — neither name it nor move
its label. Those values are:

- the tags frequent in the group and rare in the reference;
- a dominant source or studio;
- "acclaimed" or "low-rated" by median score;
- "classic" or "recent" by median year.

A group with nothing distinctive is named "mixed". The cut-offs are in `auto_name`.

An admin can set a **hand name** with `PATCH /admin/galaxy/groups/{uuid}`, and an empty
name clears it. A hand name overrides the auto name and carries onto each refit by
trained-member overlap (`galaxy_compute.carry_names`). A new group without a match shows
its auto name.

---

**Why it is this way**
- [Galaxy](../../compound-docs/2026-10-30-v0.16.5-galaxy.md): the study behind the grain, the training set, the weights, the pipeline and the name floor, and the stability backtests
