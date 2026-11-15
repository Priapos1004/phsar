/** The recommender eval's job page as data: what each figure and feature means, and the grouped
 * feature table built from a run's report — pure, so the grouping is testable without a DOM.
 *
 * The names are `recommender_compute.NAMES` and its families; one missing here renders by its
 * code with no tooltip, nothing worse. */

import type { EvalGuard, EvalPerUser, EvalWatchlistGroup, RecommenderEvalReport } from '$lib/types/api';
import { priorityLabel } from '$lib/utils/watchlist';

type Info = { label: string; tip: string };

/** A recommender eval run's verdict, as the Jobs Log and its page name it. */
export const VERDICT = { applied: 'Refit applied', held: 'Refit held back', waiting: 'Measuring only' } as const;

export const SPLITS = [
	{ key: 'time', label: 'Time split', tip: "Each user's latest 40% of picks, fitted on their earlier ones and everyone else's" },
	{ key: 'louo', label: 'Leave one user out', tip: "Each user's picks, fitted on the other users' alone" },
] as const;

/** What each figure is, then how to read it: what chance scores, where noise ends, what a sign
 * means. The noise lines are the ones the harness measured (the compound doc). */
export const METRIC_TIPS = {
	top25: 'Share of held-out picks the fit ranked in its top 25.\nBy chance: 25 out of ~1,700 candidates, about 1.5%. Each pick is one step of 1 ÷ picks.',
	tilt: "The same for the ranking's score, the fit plus the enjoyment tilt.\nBelow the plain fit means the tilt costs hits.",
	row: 'The same in the stored row, after its caps and explore slots: what the user sees.',
	liked: 'Top 25 over the picks the user rated at or above their own median.',
	median: 'The middle place of the pick among the candidates.\nBy chance: about half of them, ~850.',
	surprise: 'The chance the fit gave the actual pick, as 1 in N (e to the NLL).\nBy chance: 1 in the number of candidates, ~1,700. Lower is better, and 0.05 of NLL moves N by about 5%.',
	picks: 'Held-out picks behind the figures.',
	live: 'The weight ranking now.\nWeights act on features brought to one spread, so they compare: under ±0.1 barely matters, over ±0.5 is strong. Positive pushes a candidate up.',
	refit: "This run's refit, applied unless something holds it back.",
	change: "Refit minus live.\nUnder ±0.1 is within the weights' own noise (their typical bootstrap error is about 0.09); amber moves more. Red is a sign flip the guard holds the refit back for.",
	addsHit: 'Held-out top-25 share with it minus without it, time split / leave one user out.\nOne pick is about 0.03 of the time split and 0.01 of leave one user out, so a step or two is noise.',
	addsNll: 'Held-out NLL without it minus with it, time split / leave one user out.\nAbove 0 it helps the fit, below 0 it hurts. Its size: 0.05 is small, the watchlist adds about 0.4. Green or red when beyond noise.',
	p: 'The chance an NLL change this large comes from noise alone (paired sign flips), time split / leave one user out.\nUnder .05 is beyond noise, .05 to .2 a hint, above .2 nothing. Green and red mark a change beyond noise.',
	spread: 'How unevenly the fit serves its users: the standard deviation across users of their own top-25 share and NLL.\nLarge means some users are served much better than others.',
	perUser: "Held-out NLL of the pooled weights minus per-user ones for this family alone, time split, over every user.\nAbove 0 means letting users differ here would help; p beside it says whether that is beyond noise.",
	lift: 'How many times more often picked than choosing at random among the candidates.\n1× is no effect, under 1× picked less.',
	hazard: 'Picks per 100 days an anime spends on the list.',
	days: 'Days anime spent listed in this group, all users together.',
	listPicks: 'Picks behind the figure; under about 10 is too few to read.',
	hit10: "Share of rewatches ranked in the top 10 of the user's finished, unlisted anime.\nBy chance: 10 out of ~180, about 5%.",
	shown: 'Anime shown in the row whose next five picks have happened.',
	watched: 'Of those, the share picked within the five.',
} as const;

/** NLL as the chance it stands for: the fit gave the pick 1 in this many. */
export const oneIn = (nll: number | null | undefined): string => (nll == null ? '—' : `1 in ${Math.round(Math.exp(nll)).toLocaleString('en')}`);

export const FAMILIES: Record<string, Info> = {
	F1: { label: 'Recent picks · closeness', tip: "Galaxy closeness to the user's latest picks" },
	F2: { label: 'Recent picks · matches', tip: 'Same sector, region, studio, length or release age as the latest picks, and genre overlap' },
	F3: { label: 'Due-ness', tip: "How overdue a sector, region, length or genre is against the user's usual gap" },
	F4: { label: 'Trends', tip: "The recent shift in the user's sectors, lengths and genres" },
	F5: { label: 'Taste and popularity', tip: 'Closeness to favourites, predicted own score, MAL score and votes' },
	F6: { label: 'Commitment size', tip: 'The hours picking it would start' },
	F6x: { label: 'Watch intensity', tip: 'Its length against how much the user watched lately' },
	F7: { label: 'Continuation', tip: 'Whether it continues an anime the user started' },
	F8: { label: 'Release-age freshness', tip: "The user's preference for its release age" },
	F9: { label: 'Length preference', tip: "The user's preference for its length" },
	F10: { label: 'Finale freshness', tip: "The user's preference for how long ago its finale aired" },
	W: { label: 'Watchlist', tip: 'Its priority, how long it has been listed, and how much the list holds' },
};

export const FEATURES: Record<string, Info> = {
	F1_sim_decay10: { label: 'Closeness to recent picks', tip: 'Galaxy closeness to the last 10 picks, the newer weighing more' },
	F2_sector_lag1: { label: 'Same sector as the last pick', tip: "1 when it shares the latest pick's galaxy sector" },
	F2_region_lag1: { label: 'Same region as the last pick', tip: "1 when it shares the latest pick's galaxy region" },
	F2_genreJac_lag1: { label: 'Genre overlap with the last pick', tip: 'Share of their genres in common (Jaccard)' },
	F2_studio_lag1: { label: 'Same studio as the last pick', tip: 'A studio in common with the latest pick' },
	F2_len_lag1: { label: 'Same length as the last pick', tip: "1 when it falls in the latest pick's length bucket" },
	F2_age_lag1: { label: 'Same release age as the last pick', tip: "1 when it falls in the latest pick's release-age bucket" },
	F5_knn_pct: { label: 'Predicted own score', tip: "How the user rated its 20 nearest rated anime, as their own percentile" },
	F5_top20_sim: { label: 'Near the favourites', tip: "Galaxy closeness to the user's top-20% anime" },
	F5_mal: { label: 'MAL score', tip: 'Its MAL score, as the app shows it' },
	F5_mal_missing: { label: 'No MAL score', tip: 'MAL has no score for it' },
	F5_logvotes: { label: 'MAL votes', tip: 'How many people rated it on MAL (log)' },
	F6_loglen: { label: 'Length', tip: 'Hours picking it would start (log)' },
	F6_long: { label: 'Long', tip: '10 hours or more' },
	F7_is_cont: { label: 'Continues a started anime', tip: 'The user rated part of it and has story left' },
	F8_age_propensity: { label: 'Release-age preference', tip: "How much the user's recent picks favour its release age, over availability" },
	F9_len_propensity: { label: 'Length preference', tip: "How much the user's recent picks favour its length, over availability" },
	F10_finale_propensity: { label: 'Finale-age preference', tip: "How much the user's recent picks favour its time since the finale, over availability" },
	...Object.fromEntries([1, 2, 3].map((p) => [`W_p${p}`, { label: `Listed, ${priorityLabel(p)} priority`, tip: `On the list at ${priorityLabel(p)} priority (P${p})` }])),
	W_log_age: { label: 'Time on the list', tip: 'Days since it was listed or last changed (log)' },
	W_backlog: { label: 'List size', tip: 'Listed anime per natural pick in 30 days (log), on listed candidates only' },
	F7_own_pct: { label: 'Own score so far', tip: 'How the user rated the started anime so far, as their own percentile' },
	F7_log_days_since: { label: 'Time since last watched', tip: 'Days since the user last watched the started anime (log)' },
	// The lag features past the first, which the ranking measures but leaves out.
	...Object.fromEntries([1, 2, 3].map((k) => [`F1_sim_lag${k}`, { label: `Closeness to pick ${k} back`, tip: `Galaxy closeness to the user's pick ${k} back` }])),
	...Object.fromEntries([2, 3].flatMap((k) => ([
		['sector', `Same sector as pick ${k} back`], ['region', `Same region as pick ${k} back`],
		['genreJac', `Genre overlap with pick ${k} back`], ['studio', `Same studio as pick ${k} back`],
		['len', `Same length as pick ${k} back`], ['age', `Same release age as pick ${k} back`],
	] as const).map(([facet, label]) => [`F2_${facet}_lag${k}`, { label, tip: `As for the latest pick, for the pick ${k} back` }]))),
};

/** `recommender_compute.family`: the code a feature's name starts with, `F6x` for an interaction. */
export const familyOf = (name: string): string => (name.includes('_x_') ? 'F6x' : name.split('_')[0]);

/** The left-out families measured in a shipped family's group, because they extend it. */
const EXTENDS: Record<string, string> = { F6x: 'F6' };

export type Effect = Record<string, { hit25: number; nll: number; p: number }> | undefined;

/** The line under which a p is beyond noise: `recommender_eval.HELP_P`. */
export const BEYOND_NOISE = 0.05;
/** Whether an NLL change helps or hurts beyond noise, as the tables colour it. */
export const tone = (nll: number | null | undefined, p: number | null | undefined): 'good' | 'bad' | undefined =>
	nll == null || p == null || p >= BEYOND_NOISE || nll === 0 ? undefined : nll > 0 ? 'good' : 'bad';

/** A "would help now" item in words: a feature or family by its label, `drop …` and
 * `per-user …@λ` likewise. */
export function describe(key: string): string {
	const drop = key.match(/^drop (.+)$/);
	if (drop) return `drop ${describe(drop[1])}`;
	const perUser = key.match(/^per-user (.+)@(.+)$/);
	if (perUser) return `per-user ${perUser[1] === 'all' ? 'weights' : describe(perUser[1])} (λu ${perUser[2]})`;
	return (FEATURES[key] ?? FAMILIES[key])?.label ?? (key === 'rewatch' ? 'complete rewatches' : key);
}
/** A family's per-user fit against the pooled weights; `helps` when it would help now. */
export type PerUser = { gain: number | null; p: number; helps: boolean };

/** One row of the feature table: a family heading, one of its weights, or one of its features
 * the ranking leaves out (`held`, measured as an addition and never ranked). `helps` marks a family that would help
 * now, `flipped` a weight above the guard's line that changed sign. */
export type FeatureRow =
	| { kind: 'family'; code: string; info?: Info; held: boolean; helps: boolean; drop: boolean; effect: Effect; perUser?: PerUser }
	| { kind: 'weight'; name: string; info?: Info; live: number | undefined; refit: number; flipped: boolean; drop: boolean; effect: Effect }
	| { kind: 'held'; code: string; info: Info; helps: boolean; effect: Effect };

export function featureRows(report: RecommenderEvalReport, guards: EvalGuard[], wouldHelp: string[]): FeatureRow[] {
	const { live, refit } = report.weights;
	const flipped = new Set(guards.flatMap((g) => (g.kind === 'flip' ? [g.name] : [])));
	const helps = new Set(wouldHelp);
	const unseen = new Set(Object.keys(report.ablations));
	const take = (key: string) => (unseen.delete(key) ? report.ablations[key] : undefined);
	const perUser = (code: string): PerUser | undefined => {
		const fit = report.per_user.find((e: EvalPerUser) => e.weights === code);
		return fit && { gain: fit.gain, p: fit.p, helps: helps.has(`per-user ${code}@${fit.lam}`) };
	};

	const rows: FeatureRow[] = [];
	for (const code of new Set(Object.keys(refit).map(familyOf))) {
		rows.push({
			kind: 'family', code, info: FAMILIES[code], held: false, helps: false, drop: helps.has(`drop ${code}`),
			effect: take(code), perUser: perUser(code),
		});
		for (const name of Object.keys(refit).filter((n) => familyOf(n) === code)) {
			rows.push({
				kind: 'weight', name, info: FEATURES[name], live: live[name], refit: refit[name],
				flipped: flipped.has(name), drop: helps.has(`drop ${name}`), effect: take(name),
			});
		}
		for (const name of [...unseen].filter((key) => key !== code && familyOf(key) === code)) {
			rows.push({ kind: 'held', code: name, helps: helps.has(name), effect: take(name), info: FEATURES[name] ?? { label: name, tip: '' } });
		}
		for (const [extra, home] of Object.entries(EXTENDS)) {
			if (home === code && unseen.has(extra)) {
				rows.push({ kind: 'held', code: extra, helps: helps.has(extra), effect: take(extra), info: FAMILIES[extra] ?? { label: extra, tip: '' } });
			}
		}
	}
	// What is left extends no shipped family: a group of its own, held out.
	for (const code of [...unseen]) {
		rows.push({ kind: 'family', code, info: FAMILIES[code], held: true, helps: helps.has(code), drop: false, effect: take(code) });
	}
	return rows;
}

/** The watchlist's pooled figures as table rows, grouped by priority and by entry age: each
 * label's lift over random choice, and how often a listed anime gets picked. */
export function watchlistRows(g: EvalWatchlistGroup) {
	return (['priority', 'age'] as const).flatMap((kind) =>
		Object.entries(g.lift[kind] ?? {}).map(([label, lift]) => {
			const hazard = g.hazard[kind]?.[label];
			return {
				group: kind === 'priority' ? 'Priority' : 'Time on the list',
				label: kind === 'priority' && /^\d+$/.test(label) ? `${priorityLabel(Number(label))} priority` : label,
				lift: lift.lift, picks: lift.picks, per100: hazard?.per_100_days, days: hazard?.days,
			};
		}),
	);
}
