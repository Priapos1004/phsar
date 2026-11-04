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
- **genres, themes and demographics**: for each tag, the share of the anime's media
  carrying it, the same measure the majority rule uses;
- **source and format**: shares over the main story, with log watch hours added to format;
- **age and era**: the highest age tier and the first main-story year;
- **studios**: the most productive studios one-hot, and every other studio as a big, mid
  or small output bucket;
- **quality**: the anime's MAL score and log vote count, as the app shows them.

Each block is balanced against the others over the training set and then weighted
(`WEIGHTS`). A missing value takes the training median. The vector is stored on the star (`features`).

**Only settled anime shape the map.** An anime trains the fit when its main story has a
finished media with a MAL score. Every other anime (airing, announced, or finished but
unscored) is placed onto the fitted map instead, with `trained` false. Letting them train
behind a has-score flag builds a mixed "unrated island" and destabilises the sectors
around it.

## The fit

1. UMAP reduces the trained vectors to 10-D.
2. **Sectors** come from HDBSCAN on the 10-D, size-capped (`MAX_SECTOR_FRACTION` says
   why). A star that HDBSCAN calls noise keeps its likeliest sector and is marked
   `between`.
3. **Regions** come from Ward clustering inside each sector, about one region per
   `REGION_SIZE` stars. Ward runs on the 10-D plus MAL score and era, so a sector splits
   by quality and age as well as by content.
4. A second UMAP, fitted on the 10-D, gives the 2-D layout the map draws.

Untrained anime go through the fitted models:

- both UMAP `transform`s;
- HDBSCAN's `approximate_predict`, falling back to the membership argmax when it answers
  noise;
- the nearest region centroid in the sector's region space.

`galaxy_compute.place` does the same from the pickled models alone, for anime the map has
not seen yet.

**A refit starts from the live map.** Both UMAPs start from the stars' stored coordinates,
a newcomer beside its nearest known stars. As a result the median star moves a few percent
of the map instead of the whole map reshuffling.

Sectors still churn between fits, which is why names follow members rather than numbers.
The job reports the movement as `median_movement`.

## The rebuild job

`galaxy_rebuild`:

1. loads the catalogue, the live map's coordinates and its hand names;
2. commits, so no transaction stays open across the fit;
3. runs the fit in a spawned child (`galaxy_service.run_in_child` says why);
4. swaps the old fit for the new one in a single transaction (`replace_fit`).

A failed fit writes nothing and leaves the live map in place. The job has no maintenance
bracket, because it writes only its own tables.

### When the map is rebuilt

An admin can rebuild on demand with `POST /admin/galaxy/rebuild`; the job shows in their
bell. Otherwise `galaxy_service.ensure_map` decides. It is asked at every boot, behind the
re-embed (`main.py` says why), and by every `schedule-nightly`. It enqueues a rebuild
when the map is due:

- **there is no map**: a first deploy or a fresh database;
- **the map was built from something that has changed**: each fit records the embedding
  model it read and the versions of the libraries in its pickle (`built_from`), so a
  model swap or a library bump refits by itself;
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

`GET /browse/galaxy/{anime_uuid}/neighbours` answers the `NEIGHBOURS` stars nearest in
feature space, nearest first, each with what it shares with the one asked about
(`GalaxyNeighbourOut`). Every shared trait is weighed on one scale, the chance two anime
on the map share it anyway, so a rare genre outranks a merely close synopsis: for a genre,
studio or source the share of stars carrying it (`GalaxyDAO.trait_counts`), for the
synopsis the share of random pairs this alike (the `pair_cosine_percentiles` each fit
records). A neighbour lists the rarest `SHARED_SHOWN`, none above `SHARED_CHANCE_MAX` (the
constants say why). It is asked on demand rather than inlined in the map, so a star placed
since the map loaded has neighbours too.

## The tab

The map is drawn in the browser from that one payload, its sector colours included
(`sectorHues`); the MAL score colouring ranks by Top N%. Find an anime is the search's own
title match (`/search/anime`), kept to anime with a star. The filters ask
`/search/anime/uuids` which anime they keep, and the tab lights those.

## Names

Every group gets an **auto name** on every fit, so a fresh database needs nothing seeded.
The name lists the group's distinguishing values against a reference population: the
catalogue for a sector, the parent sector for a region. Those values are:

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
