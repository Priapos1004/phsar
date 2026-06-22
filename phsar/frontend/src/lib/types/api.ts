/** TypeScript types mirroring backend Pydantic schemas */
import type { ThemeKey } from '$lib/themes';

// Auth
export interface TokenResponse {
	access_token: string;
	token_type: string;
}

// Maintenance window status (GET /maintenance/status, public)
export interface MaintenanceStatus {
	active: boolean;
	scheduled_at: string | null; // ISO 8601
}

// Media
export interface MediaConnected {
	mal_id: number;
	mal_url: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	other_names: string[];
	media_type: string;
	relation_type: string;
	age_rating: string | null;
	description: string | null;
	original_source: string | null;
	cover_image: string | null;
	score: number | null;
	scored_by: number;
	episodes: number | null;
	anime_season_name: string | null;
	anime_season_year: number | null;
	airing_status: string;
	aired_from: string | null;
	aired_to: string | null;
	duration: string | null;
	duration_seconds: number | null;
	genres: string[];
	studio: string[];
	anime_uuid: string;
	anime_title: string;
	anime_name_eng: string | null;
	anime_name_jap: string | null;
	anime_other_names: string[];
	uuid: string;
	total_watch_time: number | null;
	age_rating_numeric: number | null;
}

// Genre name + description (GET /filters/genres) — powers genre-badge tooltips
export interface GenreOut {
	name: string;
	description: string | null;
}

// Filter options (GET /filters/options)
export interface FilterOptions {
	relation_type: string[];
	media_type: string[];
	age_rating: string[];
	airing_status: string[];
	anime_season: string[];
	genre_name: string[];
	studio_name: string[];
	score_min: number | null;
	score_max: number | null;
	scored_by_min: number | null;
	scored_by_max: number | null;
	episodes_min: number | null;
	episodes_max: number | null;
	duration_per_episode_min: number | null;
	duration_per_episode_max: number | null;
	total_watch_time_min: number | null;
	total_watch_time_max: number | null;
}

// Media detail
export interface MediaSibling {
	uuid: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	cover_image: string | null;
	media_type: string;
	relation_type: string;
	episodes: number | null;
	airing_status: string;
	anime_season_name: string | null;
	anime_season_year: number | null;
}

export interface MediaDetail extends MediaConnected {
	/** "Top N%" rank of this media's confidence-weighted MAL score among all
	 * scored media in the catalog (null when unscored). */
	score_top_percent: number | null;
	sibling_media: MediaSibling[];
	/** Insertion index for the "you are here" marker in the chronological
	 * sibling order. 0 = current media precedes every sibling, sibling_media.length = trails all. */
	current_position: number;
}

// Rating attribute enums
export type Pace = 'slow' | 'normal' | 'fast';
export type AnimationQuality = 'bad' | 'normal' | 'good' | 'very_good';
export type ThreeDAnimation = 'none' | 'partial' | 'full';
export type WatchedFormat = 'sub' | 'dub' | 'both';
export type FanService = 'none' | 'rare' | 'medium' | 'heavy';
export type DialogueQuality = 'flat' | 'normal' | 'deep';
export type CharacterDepth = 'flat' | 'normal' | 'complex';
export type EndingType = 'open' | 'closed' | 'cliffhanger';
export type EndingQuality = 'unsatisfying' | 'satisfying' | 'very_satisfying' | 'not_applicable';
export type StoryQuality = 'weak' | 'average' | 'good' | 'outstanding';
export type Originality = 'conventional' | 'unique' | 'experimental';
export type WatchStatus = 'completed' | 'on_hold' | 'dropped';

/** Watch-status options for the rating selector + display badges (single source of truth). */
export const WATCH_STATUS_OPTIONS: { value: WatchStatus; label: string }[] = [
	{ value: 'completed', label: 'Completed' },
	{ value: 'on_hold', label: 'On Hold' },
	{ value: 'dropped', label: 'Dropped' },
];

// Ratings
export interface RatingOut {
	uuid: string;
	rating: number;
	watch_status: WatchStatus;
	watched_count: number;
	episodes_watched: number | null;
	note: string | null;
	media_uuid: string;
	media_title: string;
	media_cover_image: string | null;
	anime_uuid: string;
	anime_title: string;
	pace: Pace | null;
	animation_quality: AnimationQuality | null;
	has_3d_animation: ThreeDAnimation | null;
	watched_format: WatchedFormat | null;
	fan_service: FanService | null;
	dialogue_quality: DialogueQuality | null;
	character_depth: CharacterDepth | null;
	ending_type: EndingType | null;
	ending_quality: EndingQuality | null;
	story_quality: StoryQuality | null;
	originality: Originality | null;
	created_at: string;
	modified_at: string;
}

export interface RatingCreate {
	rating: number;
	watch_status?: WatchStatus;
	episodes_watched?: number | null;
	note?: string | null;
	pace?: Pace | null;
	animation_quality?: AnimationQuality | null;
	has_3d_animation?: ThreeDAnimation | null;
	watched_format?: WatchedFormat | null;
	fan_service?: FanService | null;
	dialogue_quality?: DialogueQuality | null;
	character_depth?: CharacterDepth | null;
	ending_type?: EndingType | null;
	ending_quality?: EndingQuality | null;
	story_quality?: StoryQuality | null;
	originality?: Originality | null;
}

/** Read a dynamic attribute key from a rating object (needed because attribute keys are iterated at runtime). */
export function getRatingAttr(obj: RatingOut | RatingCreate, key: string): string | null {
	return (obj as unknown as Record<string, string | null>)[key] ?? null;
}

/**
 * True when an attribute value is a real rating, not unset or the auto-set
 * `not_applicable` sentinel (set on on_hold/dropped ratings whose ending wasn't
 * reached). Single source of truth for "count this attribute as rated" — used by
 * the per-rating card display, the distribution bars, and the overview gate so the
 * radar/bars/badges all agree.
 */
export function isAttrRated(value: string | null): boolean {
	return value !== null && value !== 'not_applicable';
}

/** Maps each rating attribute to its display label and possible values. */
export const RATING_ATTRIBUTE_OPTIONS: Record<string, { label: string; options: { value: string; label: string }[] }> = {
	pace: { label: 'Pace', options: [{ value: 'slow', label: 'Slow' }, { value: 'normal', label: 'Normal' }, { value: 'fast', label: 'Fast' }] },
	animation_quality: { label: 'Animation Quality', options: [{ value: 'bad', label: 'Bad' }, { value: 'normal', label: 'Normal' }, { value: 'good', label: 'Good' }, { value: 'very_good', label: 'Very Good' }] },
	has_3d_animation: { label: '3D Animation', options: [{ value: 'none', label: 'None' }, { value: 'partial', label: 'Partial' }, { value: 'full', label: 'Full' }] },
	watched_format: { label: 'Watched Format', options: [{ value: 'sub', label: 'Sub' }, { value: 'dub', label: 'Dub' }, { value: 'both', label: 'Both' }] },
	fan_service: { label: 'Fan Service', options: [{ value: 'none', label: 'None' }, { value: 'rare', label: 'Rare' }, { value: 'medium', label: 'Medium' }, { value: 'heavy', label: 'Heavy' }] },
	dialogue_quality: { label: 'Dialogue Quality', options: [{ value: 'flat', label: 'Flat' }, { value: 'normal', label: 'Normal' }, { value: 'deep', label: 'Deep' }] },
	character_depth: { label: 'Character Depth', options: [{ value: 'flat', label: 'Flat' }, { value: 'normal', label: 'Normal' }, { value: 'complex', label: 'Complex' }] },
	ending_type: { label: 'Ending Type', options: [{ value: 'open', label: 'Open' }, { value: 'closed', label: 'Closed' }, { value: 'cliffhanger', label: 'Cliffhanger' }] },
	ending_quality: { label: 'Ending Quality', options: [{ value: 'unsatisfying', label: 'Unsatisfying' }, { value: 'satisfying', label: 'Satisfying' }, { value: 'very_satisfying', label: 'Very Satisfying' }, { value: 'not_applicable', label: 'Not Applicable' }] },
	story_quality: { label: 'Story Quality', options: [{ value: 'weak', label: 'Weak' }, { value: 'average', label: 'Average' }, { value: 'good', label: 'Good' }, { value: 'outstanding', label: 'Outstanding' }] },
	originality: { label: 'Originality', options: [{ value: 'conventional', label: 'Conventional' }, { value: 'unique', label: 'Unique' }, { value: 'experimental', label: 'Experimental' }] },
};

// Anime search result (aggregated)
export interface RelationTypeSummary {
	relation_type: string;
	count: number;
}

export interface MediaTypeSummary {
	media_type: string;
	count: number;
}

/** Shared aggregated fields for anime search results and detail views. */
export interface AnimeAggregatedBase {
	uuid: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	cover_image: string | null;
	avg_score: number | null;
	avg_scored_by: number;
	total_episodes: number | null;
	total_watch_time: number | null;
	media_count: number;
	relation_types: RelationTypeSummary[];
	media_types: MediaTypeSummary[];
	genres: string[];
	studios: string[];
	season_start: string | null;
	season_end: string | null;
	airing_status: string;
	has_upcoming: boolean;
	age_rating_numeric: number | null;
	is_finished: boolean;
}

export interface AnimeSearchResult extends AnimeAggregatedBase {}

// Anime detail
export interface AnimeMediaItem {
	uuid: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	cover_image: string | null;
	media_type: string;
	relation_type: string;
	score: number | null;
	scored_by: number;
	episodes: number | null;
	airing_status: string;
	anime_season_name: string | null;
	anime_season_year: number | null;
	total_watch_time: number | null;
	age_rating_numeric: number | null;
	genres: string[];
	studios: string[];
}

export interface AnimeDetail extends AnimeAggregatedBase {
	other_names: string[];
	description: string | null;
	/** "Top N%" rank of this anime's confidence-weighted MAL score among all
	 * scored anime in the catalog (null when unscored). */
	score_top_percent: number | null;
	media: AnimeMediaItem[];
}

// Search token (POST /filters/create-token)
export interface SearchTokenResponse {
	token: string;
}

// User Settings
export interface UserSettings {
	theme: ThemeKey;
	name_language: 'english' | 'japanese' | 'romaji';
	default_search_view: 'anime' | 'media';
	rating_step: '0.5' | '0.25' | '0.1' | '0.01';
	spoiler_level: 'off' | 'blur' | 'hide';
}

export type UserSettingsUpdate = Partial<UserSettings>;

// Spoiler visibility
export interface SpoilerVisibility {
	visible_media_uuids: string[];
}

// Admin — Story completion
export interface FinishedAnimeItem {
	uuid: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	cover_image: string | null;
	marked_by_username: string | null;
	marked_at: string;
}

// Admin — Merge candidates
export interface MergeCandidateAnimeSummary {
	uuid: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	media_count: number;
	studios: string[];
	earliest_year: number | null;
	earliest_aired_from: string | null;
	rating_count: number;
}

export interface PendingReclassification {
	media_uuid: string;
	title: string;
	old_relation_type: string;
	new_relation_type: string;
}

export interface MergeCandidateListItem {
	uuid: string;
	similarity_score: number;
	detected_by: string;
	created_at: string;
	/** Set only in the dismissed-decisions list; null for pending rows. */
	dismissed_at: string | null;
	anime_a: MergeCandidateAnimeSummary;
	anime_b: MergeCandidateAnimeSummary;
	pending_reclassifications: PendingReclassification[];
}

export interface MergeBackfillResult {
	inserted: number;
}

// Admin — Split candidates
export interface SplitClusterMember {
	media_uuid: string;
	mal_id: number;
	title: string;
	media_type: string;
	relation_type: string;
}

export interface SplitClusterPreview {
	suggested_anchor_mal_id: number;
	members: SplitClusterMember[];
	substance_member_mal_ids: number[];
	// (source_mal_id, target_mal_id, normalized_relation) tuples
	bridge_edges: [number, number, string][];
}

export interface SplitCandidateListItem {
	uuid: string;
	detected_by: string;
	created_at: string;
	/** Set only in the dismissed-decisions list; null for pending rows. */
	dismissed_at: string | null;
	source_anime: MergeCandidateAnimeSummary;
	clusters: SplitClusterPreview[];
}

export interface SplitResult {
	surviving_anime_uuid: string;
	new_anime_uuids: string[];
}

export interface SplitBackfillResult {
	inserted: number;
}

// Admin — Registration tokens
export interface RegistrationTokenListItem {
	uuid: string;
	token: string;
	role: string;
	status: 'active' | 'used' | 'expired';
	created_by: string;
	created_at: string;
	expires_on: string;
	used_by: string | null;
	used_at: string | null;
}

// Jobs (content pipeline)
export type JobKind = 'user_scrape' | 'update_sweep' | 'seasonal_sweep' | 'backup' | 'restore';
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

// Mirrors backend `job_worker.ERROR_CATEGORY_*`. Keep both sides in sync —
// the union is the compile-time contract that catches drift.
export type JobErrorCategory = 'upstream_outage' | 'backup_disk_full' | 'backup_corrupt';

export interface JobResultSummary {
	retryable?: boolean;
	error_category?: JobErrorCategory;
	[key: string]: unknown;
}

// Backup dispatcher stamps these into result_summary on success. Typed as a
// supertype of JobResultSummary so the bell can read fields directly via `?.`
// without a runtime guard (Job.result_summary is still typed JobResultSummary).
export interface BackupResultSummary extends JobResultSummary {
	filename?: string;
	size_bytes?: number;
	integrity?: BackupIntegrity;
	source?: BackupSource;
	deduped_against?: string | null;
}

// One field's before/after on the update_sweep detail page. `old`/`new`
// are typed `unknown` because the JSONB store erases types — the
// renderer narrows per field.
export interface UpdateSweepFieldChange {
	field: string;
	old: unknown;
	new: unknown;
}

export interface UpdateSweepMediaChange {
	anime_id: number;
	anime_uuid: string;
	anime_title: string;
	// name_eng / name_jap are optional so the detail page can fall back
	// to the romaji title for v2 rows scraped before the name-language
	// addition (or media rows MAL never emitted alt-titles for).
	anime_name_eng?: string | null;
	anime_name_jap?: string | null;
	media_id: number;
	media_uuid: string;
	media_mal_id: number;
	media_title: string;
	media_name_eng?: string | null;
	media_name_jap?: string | null;
	media_relation_type: string;
	dynamic: UpdateSweepFieldChange[];
	static: UpdateSweepFieldChange[];
	genre_drift: UpdateSweepM2MDrift | null;
	studio_drift: UpdateSweepM2MDrift | null;
}

// Shape the genre/studio drift detector emits per-media. Mirrors the
// backend's `_emit_drift_report` plain dict.
//
// `kind` literal union covers both v2 (pre-v0.14.5) and v3+ vocabularies
// so the frontend renders historical rows correctly:
//   v2 (sweep job version 2): additions_applied, additions_unknown,
//     removal_or_replacement, any_change — most kinds meant "logged but
//     not applied".
//   v3 (sweep job version ≥ 3, post-v0.14.5): applied,
//     applied_with_unknowns — all drift now applies; the only "not
//     applied" subset is unknown genre tags awaiting seeder updates.
export interface UpdateSweepM2MDrift {
	field: 'genres' | 'studios';
	media_mal_id: number;
	media_title: string;
	kind:
		| 'applied'
		| 'applied_with_unknowns'
		| 'additions_applied'
		| 'additions_unknown'
		| 'removal_or_replacement'
		| 'any_change';
	old: string[];
	new: string[];
	unknown_tags: string[];
}

export interface UpdateSweepUmbrellaReclassified {
	mal_id: number;
	old: string;
	new: string;
}

export interface UpdateSweepUmbrellaChange {
	anime_id: number;
	anime_uuid: string;
	anime_title: string;
	anime_name_eng?: string | null;
	anime_name_jap?: string | null;
	fields: UpdateSweepFieldChange[];
	anchor_changed: boolean;
	old_anchor_mal_id: number;
	new_anchor_mal_id: number;
	embedding_regenerated: boolean;
	reclassified: UpdateSweepUmbrellaReclassified[];
}

export interface UpdateSweepCounters {
	// v2–v4: anime-grained refresh count. Dropped in v5 (renamed →
	// media_refreshed) since the work unit is now the media row.
	anime_refreshed?: number;
	// v5+: individual media refreshed (the headline workload), distinct
	// anime touched, and media that were present in a touched umbrella but
	// not individually due (the work the media-level selection avoided).
	media_refreshed?: number;
	anime_touched?: number;
	media_skipped_fresh?: number;
	// v2–v4 only: per-anime rollups. Dropped in v5 — media_with_* below
	// carries the signal now.
	anime_with_dynamic_changes?: number;
	anime_with_static_changes?: number;
	media_with_dynamic_changes: number;
	media_with_static_changes: number;
	umbrella_reclassed: number;
	probe_succeeded: number;
	probe_failed: number;
	probe_attached_anime_count: number;
	// v6+: media-grained total of media the relations probe attached this run
	// (probe_attached_anime_count is anime-grained). Pre-v6 rows omit it.
	probe_attached_media_count?: number;
	// v3+: Studio rows deleted at sweep end because drift removals left
	// them with no media links. v2 rows omit it (renders as 0).
	orphaned_studios_removed?: number;
	// v4+: anime selected but skipped because step-1 refresh raised. Pre-v4
	// rows omit it — render "—" (not tracked), NOT 0 (which would falsely
	// claim zero failures on sweeps that never recorded them).
	step1_failed?: number;
}

// One step-1 refresh that raised and was skipped (v4+ update_sweep).
export interface UpdateSweepStep1Failure {
	anime_uuid: string;
	title: string;
	// name_eng / name_jap (v6+) so the detail page can render the title in the
	// admin's name language via resolveTitle; pre-v6 rows omit them (falls back
	// to the romaji title).
	name_eng?: string | null;
	name_jap?: string | null;
	error_category: string | null;
	error_message: string;
}

// One step-2 relations probe that raised and was skipped (v5+ update_sweep).
// Identical shape to UpdateSweepStep1Failure.
export type UpdateSweepProbeFailure = UpdateSweepStep1Failure;

// One anime the step-2 relations probe attached media to (v6+ update_sweep),
// with the new media listed so the detail page can link each back to its
// source anime.
export interface UpdateSweepProbeAttached {
	anime_uuid: string;
	title: string;
	name_eng?: string | null;
	name_jap?: string | null;
	media: { media_uuid: string; title: string; name_eng?: string | null; name_jap?: string | null }[];
}

// update_sweep result_summary v2+ shape. v1 rows omit these fields
// entirely — renderers must check `row.version >= 2` before reading.
// `unknown_genre_tags` is v3+; v2 rows don't carry it (the Jobs Log
// tint just won't fire for those historical sweeps). `step1_failures`
// is v4+; `probe_failures` is v5+.
export interface UpdateSweepResultSummary extends JobResultSummary {
	counters?: UpdateSweepCounters;
	media_changes?: UpdateSweepMediaChange[];
	anime_umbrella_changes?: UpdateSweepUmbrellaChange[];
	unknown_genre_tags?: string[];
	step1_failures?: UpdateSweepStep1Failure[];
	probe_failures?: UpdateSweepProbeFailure[];
	// v6+: anime the relations probe attached new media to this run.
	probe_attached_anime?: UpdateSweepProbeAttached[];
	merge_detect_failed?: boolean;
	cache_recompute_failed?: boolean;
}

export interface Job {
	uuid: string;
	kind: JobKind;
	// Per-kind result_summary schema version (registered in
	// `app/core/job_versions.py`). Renderers switch on `(kind, version)`
	// so historical rows keep parsing while we evolve newer payloads.
	version: number;
	status: JobStatus;
	payload: Record<string, unknown>;
	stage: string | null;
	items_total: number | null;
	items_done: number;
	result_summary: JobResultSummary | null;
	error_message: string | null;
	created_at: string;
	started_at: string | null;
	finished_at: string | null;
}

// Admin — Backups
export type BackupIntegrity = 'ok' | 'corrupt' | 'unknown';
export type BackupSource = 'manual' | 'cron' | 'pre_restore' | 'upload';

export interface BackupMetadata {
	filename: string;
	size_bytes: number;
	created_at: string;
	integrity: BackupIntegrity;
	source: BackupSource;
	content_hash?: string | null;
	is_current?: boolean;
	// Admin display name; non-empty pins the dump against auto-retention.
	name?: string | null;
	// Pre-restore snapshot: filename of the backup restored right after it.
	restored_to?: string | null;
	// Stamped on the current row: the pre-restore snapshot it superseded.
	previous_state?: string | null;
}

// Admin Overview stats — aggregate counts shown on the Overview tab
export interface AdminCatalogStats {
	anime_count: number;
	media_count: number;
	anime_added_7d: number;
	media_added_7d: number;
}

export interface AdminJobKindStats {
	kind: JobKind;
	succeeded: number;
	failed: number;
	retryable_failed: number;
}

export interface AdminJobsStats {
	by_kind: AdminJobKindStats[];
}

export interface AdminActivityStats {
	active_users: number;
	new_ratings: number;
	scrapes_submitted: number;
}

// Mutually-exclusive cycle-membership bucket counts in priority cascade
// — sum equals total anime count, so the card can render each bucket as a
// share. Membership (not due-ness): counts stay stable across sweeps.
export interface AdminSweepTierBreakdown {
	airing_now: number;
	stabilizing: number;
	// Per-check breakdown of the stabilizing total (JSON object keys are
	// strings: "0", "1", … up to SWEEP_STABILIZE_THRESHOLD-1).
	stabilizing_by_check: Record<string, number>;
	weekly_cycle: number;
	long_cycle: number;
}

export interface AdminOverviewStats {
	catalog: AdminCatalogStats;
	jobs_7d: AdminJobsStats;
	activity_7d: AdminActivityStats;
	// `sweep_tiers` = anime cycle-membership; `media_sweep_tiers` = the same
	// cascade at media grain (v0.14.8, refresh selection is media-level).
	// The Overview SweepTiersCard toggles between them.
	sweep_tiers: AdminSweepTierBreakdown;
	media_sweep_tiers: AdminSweepTierBreakdown;
}

// Admin Jobs Log — paginated all-jobs view with flattened requested_by.
// `parent_job_uuid` is set on seasonal-sweep children so the Jobs Log can
// collapse them under the sweep parent expander.
export interface AdminJobResponse extends Job {
	requested_by_username: string | null;
	parent_job_uuid: string | null;
}

export interface AdminJobsPage {
	items: AdminJobResponse[];
	total: number;
	limit: number;
	offset: number;
}

// Admin bell pinned curation reminder — pending counts only, no detail
export interface CurationPendingCounts {
	merge: number;
	split: number;
}
