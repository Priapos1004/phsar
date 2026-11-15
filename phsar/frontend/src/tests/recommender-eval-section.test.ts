import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import RecommenderEvalSection from '../lib/components/admin/RecommenderEvalSection.svelte';
import { featureRows } from '../lib/utils/recommenderEval';
import type { EvalHeldOut, RecommenderEvalReport, RecommenderEvalSummary } from '../lib/types/api';

const heldOut = (hit25: number, nll: number): EvalHeldOut => ({
	logit: { n: 36, hit25, liked_hit25: 0.5, median_rank: 21 },
	score: { n: 36, hit25 },
	row: { n: 36, hit25 },
	nll,
	nll_se: 0.26,
});

const effect = (nll: number, p = 0.01) => ({ time: { hit25: 0.01, nll, p }, louo: { hit25: 0.02, nll, p } });

const report: RecommenderEvalReport = {
	decisions: { total: 88 },
	candidates_mean: 1674.7,
	given: { time: heldOut(0.583, 5.165) },
	refit: { time: heldOut(0.556, 5.304) },
	baseline: { time: heldOut(0.111, 6.302) },
	weights: {
		live: { F1_sim_decay10: 0.33, F5_top20_sim: 0.65, F5_mal_missing: -0.14, F6_loglen: -0.13, W_p1: 0.57, W_backlog: 0.77 },
		refit: { F1_sim_decay10: 0.3, F5_top20_sim: -0.12, F5_mal_missing: -0.15, F6_loglen: 0.02, W_p1: 0.55, W_backlog: 0.74 },
	},
	ablations: {
		F1: effect(0.02), F5: effect(0.14), F6: effect(0.04), W: effect(0.43, 0.00005), W_backlog: effect(0.14),
		F5_mal_missing: { time: { hit25: 0, nll: -0.06, p: 0.02 }, louo: { hit25: 0, nll: -0.01, p: 0.4 } },
		F3: effect(0.12), F4: effect(-0.06, 0.3), F6x: effect(-0.01, 0.6), F1_sim_lag2: effect(-0.02, 0.5),
	},
	per_user: [
		{ weights: 'all', lam: 10, gain: -0.08, p: 0.4, ...heldOut(0.5, 5.381) },
		{ weights: 'W', lam: 3, gain: 0.1, p: 0.01, ...heldOut(0.6, 5.2) },
	],
	rewatch: { decisions: 13, candidates_mean: 183.9, time: { n: 6, family: { hit10: 0.17, median_rank: 30 }, own_score: { hit10: 0.33, median_rank: 25 }, p: 0.4 } },
	online: { judged: 4, waiting: 22, by_reason: { fresh: { judged: 4, watched: 1, share: 0.25 } } },
	watchlist: null,
	seconds: { decisions: 8.4 },
};

const held: RecommenderEvalSummary = {
	verdict: 'held',
	guards: [
		{ kind: 'nll', split: 'time', change: 0.31, margin: 0.05, n: 80, tripped: true },
		{ kind: 'flip', name: 'F5_top20_sim', live: 0.65, refit: -0.12, tripped: true },
	],
	log: { picks: 40, needed: 30, users: 2, users_needed: 2, per_user_needed: 14 },
	fit: null,
	would_help: ['F3', 'per-user W@3', 'drop F5_mal_missing'],
	report,
};

const row = (key: string) => document.querySelector(`tr[data-row="${key}"]`)!;

describe('featureRows', () => {
	it('groups each weight under its family, with what the family leaves out beneath it', () => {
		const rows = featureRows(report, held.guards!, ['F3']);
		expect(rows.map((r) => `${r.kind}:${r.kind === 'weight' ? r.name : r.code}`)).toEqual([
			'family:F1', 'weight:F1_sim_decay10', 'held:F1_sim_lag2',
			'family:F5', 'weight:F5_top20_sim', 'weight:F5_mal_missing',
			'family:F6', 'weight:F6_loglen', 'held:F6x',
			'family:W', 'weight:W_p1', 'weight:W_backlog',
			'family:F3', 'family:F4',
		]);
	});

	it('marks a flipped weight, a held-out family and one that would help, and carries each effect', () => {
		const rows = featureRows(report, held.guards!, held.would_help!);
		const find = (key: string) => rows.find((r) => (r.kind === 'weight' ? r.name : r.code) === key)!;
		expect(find('F5_top20_sim')).toMatchObject({ flipped: true });
		expect(find('W_p1')).toMatchObject({ flipped: false, effect: undefined });
		expect(find('W_backlog').effect).toEqual(effect(0.14));
		expect(find('F3')).toMatchObject({ held: true, helps: true });
		expect(find('F4')).toMatchObject({ held: true, helps: false });
		expect(find('F1')).toMatchObject({ held: false, helps: false });
	});
});

describe('RecommenderEvalSection', () => {
	it('leads with the verdict and every guard it tripped', () => {
		render(RecommenderEvalSection, { summary: held });
		expect(screen.getByRole('heading', { name: 'Refit held back' })).toBeTruthy();
		expect(screen.getByText(/Held-out NLL on the time split \+0\.310 over 80 picks/)).toBeTruthy();
		expect(screen.getByText(/F5_top20_sim flipped sign: 0\.65 live, -0\.12 refit/)).toBeTruthy();
		expect(screen.getByText(/Would help now: Due-ness, per-user Watchlist \(λu 3\), drop No MAL score/)).toBeTruthy();
		expect(screen.getByText(/Took replaying picks 8\.4 s\./)).toBeTruthy();
		expect(screen.getByText('Fresh', { selector: 'td' })).toBeTruthy(); // the row's reasons as the tiles name them
	});

	it('shows held-out rows in italics and flags what flipped or would help, and nothing else', () => {
		render(RecommenderEvalSection, { summary: held });
		expect(row('F5_top20_sim').className).toContain('bg-amber');
		expect(row('W_p1').className).not.toContain('bg-amber');
		expect(row('F3').className).toContain('bg-amber');
		expect(row('F3').className).toContain('italic');
		expect(row('F6x').className).toContain('italic');
		expect(row('F6').className).not.toContain('italic');
	});

	it("shows each family's per-user fit beside it, flagging one that would help, and the per-user weights in quality", () => {
		render(RecommenderEvalSection, { summary: held });
		const cell = (code: string) => document.querySelector(`td[data-per-user="${code}"]`)!;
		expect(cell('W').textContent).toContain('+0.100 · p 0.010');
		expect(cell('W').className).toContain('bg-amber');
		expect(cell('F5').textContent?.trim()).toBe('');
		const perUser = [...document.querySelectorAll('tr')].find((r) => r.textContent?.startsWith('Per-user weights, λu 10'))!;
		expect(perUser.textContent).toContain('50%');
		expect(row('W').textContent).toContain('<.001 / <.001');
		expect(row('F1_sim_lag2').textContent).toContain('Closeness to pick 2 back');
	});

	it('reads quality as shares and chances, the baseline beside each', () => {
		render(RecommenderEvalSection, { summary: held });
		const time = [...document.querySelectorAll('tr')].find((r) => r.textContent?.startsWith('Time split'))!;
		expect(time.textContent).toContain('56%baseline 11%');
		expect(time.textContent).toContain(`1 in ${Math.round(Math.exp(5.304))}baseline 1 in ${Math.round(Math.exp(6.302))}`);
	});

	it('lays the watchlist out as a table by priority and time on the list', () => {
		render(RecommenderEvalSection, {
			summary: { ...held, report: { ...report, watchlist: {
				picks: 76, listed_share: 0.68,
				lift: { priority: { '1': { lift: 29, picks: 30 }, unlisted: { lift: 0.34, picks: 24 } }, age: { '<=7d': { lift: 22.5, picks: 9 } } },
				hazard: { priority: { '1': { per_100_days: 0.68, picks: 30, days: 4412 } }, age: {} },
			} } },
		});
		const rows = [...document.querySelectorAll('tr')].map((r) => r.textContent?.trim());
		expect(rows).toContain('Priority');
		expect(rows).toContain('High priority29.00×300.684412');
		expect(rows).toContain('unlisted0.34×24——');
		expect(rows).toContain('Time on the list');
		expect(screen.getByText(/76 picks since the log began, 68% of them listed at the time/)).toBeTruthy();
	});

	it('colours what is beyond noise: green helps, red hurts, per split', () => {
		render(RecommenderEvalSection, { summary: held });
		const tones = (key: string) => [...row(key).querySelectorAll('span[data-tone]')].map((s) => s.getAttribute('data-tone'));
		expect(tones('W')).toEqual(['good', 'good']);
		expect(tones('F5_mal_missing')).toEqual(['bad']); // the second split is within noise: no tone
		expect(row('F5_mal_missing').textContent).toContain('★ dropping it would help now');
		expect(row('F1_sim_lag2').querySelectorAll('span[data-tone]')).toHaveLength(0);
	});

	it('colours a weight change red when the guard holds the refit back for it, amber past its noise', () => {
		render(RecommenderEvalSection, { summary: held });
		const change = (key: string) => row(key).querySelectorAll('td')[3];
		expect(change('F5_top20_sim').className).toContain('text-destructive');
		expect(change('F6_loglen').className).toContain('text-amber');
		expect(change('W_p1').className).not.toContain('text-amber');
		expect(change('W_p1').className).not.toContain('text-destructive');
	});

	it('shows how unevenly the refit serves its users', () => {
		render(RecommenderEvalSection, {
			summary: { ...held, report: { ...report, refit: { time: { ...heldOut(0.556, 5.304), users: 2, hit25_sd: 0.12, nll_sd: 0.4 } } } },
		});
		const time = [...document.querySelectorAll('tr')].find((r) => r.textContent?.startsWith('Time split'))!;
		expect(time.textContent).toContain('±12 pts · ±0.40 NLL');
	});

	it('says how far the log has to go while it waits', () => {
		render(RecommenderEvalSection, {
			summary: { ...held, verdict: 'waiting', guards: [], log: { picks: 12, needed: 30, users: 1, users_needed: 2, per_user_needed: 14 } },
		});
		expect(screen.getByRole('heading', { name: 'Measuring only' })).toBeTruthy();
		expect(screen.getByText(/covers 12 of the 30 picks a refit needs, and 1 of the 2 users it needs have the 14 logged picks to count/)).toBeTruthy();
		expect(screen.getByText('No earlier run of this code to compare with.')).toBeTruthy();
	});

	it('shows only the cards its summary carries', () => {
		render(RecommenderEvalSection, { summary: { verdict: 'applied', guards: [] } });
		expect(screen.getByRole('heading', { name: 'Refit applied' })).toBeTruthy();
		expect(screen.queryByRole('heading', { name: 'Features' })).toBeNull();
		expect(screen.queryByRole('heading', { name: 'Quality' })).toBeNull();
	});
});
