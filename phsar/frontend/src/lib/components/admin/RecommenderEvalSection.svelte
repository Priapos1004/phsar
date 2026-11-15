<script lang="ts">
	/* The recommender eval's report on its job page: the verdict and what decided it, how good the
	   refit is, then its features and what is measured beside them. What each figure means is
	   docs/features/recommender.md, "Measuring it"; the tooltips, with how to read each value, and
	   the feature table's grouping are `utils/recommenderEval.ts`. Aggregates only, as everywhere
	   on the admin panel. Every card shows only when its data is there, never by the job's status. */
	import type { Snippet } from 'svelte';
	import * as Card from '$lib/components/ui/card';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import * as cls from '$lib/styles/classes';
	import { describe, featureRows, METRIC_TIPS, oneIn, SPLITS, tone, VERDICT, watchlistRows, type Effect } from '$lib/utils/recommenderEval';
	import { REASON_STYLE } from '$lib/utils/recommendation';
	import type { EvalRanks, EvalTop, RecommendationKind, RecommenderEvalSummary } from '$lib/types/api';

	let { summary }: { summary: RecommenderEvalSummary } = $props();
	let report = $derived(summary.report);

	const STEPS: Record<string, string> = { decisions: 'replaying picks', fits: 'fitting', rewatch_online: 'rewatches and the row' };
	const TONE = { good: 'text-emerald-600 font-medium', bad: 'text-destructive font-medium' };

	const fixed = (x: number | null | undefined, digits = 3) => (x == null ? '—' : x.toFixed(digits));
	const signed = (x: number | null | undefined, digits = 3) => (x == null ? '—' : `${x > 0 ? '+' : ''}${x.toFixed(digits)}`);
	const pct = (x: number | null | undefined) => (x == null ? '—' : `${Math.round(x * 100)}%`);
	/** A p as the sign flips can tell it (`recommender_eval.FLIPS` of them): none as extreme reads as under .001. */
	const pValue = (x: number | null | undefined) => (x == null ? '—' : x < 0.001 ? '<.001' : x.toFixed(3));
	/** One cell per split, time / leave one user out. */
	const bySplit = (effect: Effect, value: (e: { hit25: number; nll: number; p: number }) => string) =>
		effect ? SPLITS.map((s) => (effect[s.key] ? value(effect[s.key]) : '—')).join(' / ') : '';
	/** The NLL change per split, each coloured by whether it is beyond noise. */
	const nllBySplit = (effect: Effect) =>
		effect ? SPLITS.map((s) => ({ key: s.key, text: effect[s.key] ? signed(effect[s.key].nll) : '—', tone: tone(effect[s.key]?.nll, effect[s.key]?.p) })) : [];
	/** A weight's change: red when the flip guard trips on it, amber past the weights' own noise. */
	const changeTone = (row: { flipped: boolean; live: number | undefined; refit: number }) =>
		row.flipped ? 'text-destructive font-medium' : Math.abs(row.refit - (row.live ?? 0)) >= 0.1 ? 'text-amber-600 font-medium' : '';
	const spread = (x: { hit25_sd?: number; nll_sd?: number }) =>
		x.hit25_sd == null ? '—' : `±${Math.round(x.hit25_sd * 100)} pts · ±${fixed(x.nll_sd, 2)} NLL`;

	/** A figure with the baseline's beside it. */
	type Pair = [string, string?];
	type Fit = { logit: EvalRanks; score: EvalRanks; row?: EvalRanks; nll: number | null; hit25_sd?: number; nll_sd?: number };
	const qualityCells = (r: Fit, b?: Fit): Pair[] => {
		const both = (value: (x: Fit) => string): Pair => [value(r), b && value(b)];
		return [
			both((x) => pct(x.logit.hit25)), [pct(r.score.hit25)], [pct(r.row?.hit25)], [pct(r.logit.liked_hit25)],
			both((x) => fixed(x.logit.median_rank, 0)), both((x) => oneIn(x.nll)), [spread(r)], [String(r.logit.n)],
		];
	};
	// The pooled refit on both tests, then the per-user weights on the one they have.
	let quality = $derived([
		...SPLITS.flatMap((s) => {
			const r = report?.refit[s.key];
			return r ? [{ key: s.key, label: s.label, tip: s.tip as string, sub: false, cells: qualityCells(r, report?.baseline[s.key]) }] : [];
		}),
		...(report?.per_user ?? []).filter((e) => e.weights === 'all').map((e) => ({
			key: `all@${e.lam}`, label: `Per-user weights, λu ${e.lam}`, sub: true, cells: qualityCells(e),
			tip: `Every weight fitted per user, pulled toward the pooled ones by λu; time split, over every user. ${signed(e.gain)} NLL against pooled, p ${pValue(e.p)}.`,
		})),
	]);

	let features = $derived(report ? featureRows(report, summary.guards ?? [], summary.would_help ?? []) : []);

	let rewatch = $derived.by(() => {
		const r = report?.rewatch;
		if (!r) return [];
		return SPLITS.flatMap((s) => {
			const v = r[s.key];
			if (typeof v !== 'object' || !v.n || !v.family || !v.own_score) return [];
			const top = (t: EvalTop) => [pct(t.hit10), fixed(t.median_rank, 0)];
			return [[s.label, String(v.n), ...top(v.family), ...top(v.own_score), fixed(v.p)]];
		});
	});

	let online = $derived(
		Object.entries(report?.online.by_reason ?? {}).map(([reason, o]) => [
			REASON_STYLE[reason as RecommendationKind]?.label ?? reason, String(o.judged), String(o.watched), pct(o.share),
		]),
	);

	let watchlist = $derived(report?.watchlist ? watchlistRows(report.watchlist) : []);
</script>

{#snippet hint(label: string, tip: string | undefined)}
	{#if tip}<Tooltip text={tip} class={cls.tooltipHint} contentClass="whitespace-pre-line">{label}</Tooltip>{:else}{label}{/if}
{/snippet}

{#snippet head(columns: [string, string?][])}
	<thead>
		<tr class="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border">
			{#each columns as [label, tip], i (i)}
				<th class="py-2 pr-3 font-medium whitespace-nowrap">{@render hint(label, tip)}</th>
			{/each}
		</tr>
	</thead>
{/snippet}

{#snippet table(columns: [string, string?][], rows: string[][])}
	<div class="overflow-x-auto">
		<table class="w-full text-sm">
			{@render head(columns)}
			<tbody>
				{#each rows as row, i (i)}
					<tr class="border-b border-border/50 tabular-nums text-card-foreground">
						{#each row as cell, j (j)}<td class="py-1.5 pr-3 whitespace-nowrap">{cell}</td>{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/snippet}

{#snippet card(title: string, note: string | null, body: Snippet)}
	<Card.Root>
		<Card.Header class="space-y-1">
			<h2 class="text-lg font-semibold text-card-foreground">{title}</h2>
			{#if note}<p class="text-sm text-muted-foreground">{note}</p>{/if}
		</Card.Header>
		<Card.Content>{@render body()}</Card.Content>
	</Card.Root>
{/snippet}

{#if summary.verdict}
	{#snippet verdict()}
		<ul class="space-y-1.5 text-sm text-card-foreground">
			{#if summary.verdict === 'waiting' && summary.log}
				<li>
					The watchlist log covers {summary.log.picks} of the {summary.log.needed} picks a refit needs, and
					{summary.log.users} of the {summary.log.users_needed} users it needs have the {summary.log.per_user_needed} logged
					picks to count.
				</li>
			{/if}
			{#each summary.guards ?? [] as guard (guard.kind === 'nll' ? guard.split : guard.name)}
				<li class={guard.tripped ? 'font-medium text-destructive' : ''}>
					{#if guard.kind === 'nll'}
						{guard.tripped ? '⚠ ' : ''}Held-out NLL on the {guard.split} split {signed(guard.change)} over
						{guard.n} picks the last run also tested; {fixed(guard.margin)} allowed.
					{:else}
						⚠ {guard.name} flipped sign: {fixed(guard.live, 2)} live, {fixed(guard.refit, 2)} refit.
					{/if}
				</li>
			{:else}
				<li class="text-muted-foreground">No earlier run of this code to compare with.</li>
			{/each}
			{#if summary.would_help?.length}
				<li class="font-medium">Would help now: {summary.would_help.map(describe).join(', ')}, beyond noise three runs in a row.</li>
			{/if}
			<li class="text-muted-foreground">
				Ranking with {summary.fit ? `fit ${summary.fit.slice(0, 8)}` : 'the committed weights'}.
				{#if report}{report.decisions.total} decisions, {report.candidates_mean} candidates each.{/if}
				{#if report?.seconds}
					Took {Object.entries(report.seconds).map(([step, s]) => `${STEPS[step] ?? step} ${s} s`).join(', ')}.
				{/if}
			</li>
		</ul>
	{/snippet}
	{@render card(VERDICT[summary.verdict], null, verdict)}
{/if}

{#if quality.length}
	{#snippet body()}
		<div class="overflow-x-auto">
			<table class="w-full text-sm">
				{@render head([['Test'], ['In top 25', METRIC_TIPS.top25], ['With the tilt', METRIC_TIPS.tilt], ['In the row', METRIC_TIPS.row],
					['Liked in top 25', METRIC_TIPS.liked], ['Median place', METRIC_TIPS.median], ['Chance of the pick', METRIC_TIPS.surprise],
					['Across users', METRIC_TIPS.spread], ['Picks', METRIC_TIPS.picks]])}
				<tbody>
					{#each quality as q (q.key)}
						<tr class="border-b border-border/50 tabular-nums {q.sub ? 'text-xs text-muted-foreground' : 'text-card-foreground'}">
							<td class="py-1.5 pr-3 whitespace-nowrap {q.sub ? 'pl-4' : ''}">{@render hint(q.label, q.tip)}</td>
							{#each q.cells as [value, baseline], j (j)}
								<td class="py-1.5 pr-3 whitespace-nowrap">
									{value}{#if baseline}<span class="ml-1.5 text-xs text-muted-foreground">baseline {baseline}</span>{/if}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/snippet}
	{@render card(
		'Quality',
		"How well this run's refit ranks picks it never saw, on two tests, beside the similarity baseline it has to beat; below, the same with per-user weights.",
		body,
	)}
{/if}

{#if features.length}
	{#snippet body()}
		<div class="overflow-x-auto">
			<table class="w-full text-sm">
				{@render head([['Feature'], ['Live', METRIC_TIPS.live], ['Refit', METRIC_TIPS.refit], ['Change', METRIC_TIPS.change],
					['Adds hit@25', METRIC_TIPS.addsHit], ['Adds NLL', METRIC_TIPS.addsNll], ['p-value', METRIC_TIPS.p], ['Per user', METRIC_TIPS.perUser]])}
				<tbody>
					{#each features as row, i (i)}
						{@const held = row.kind === 'held' || (row.kind === 'family' && row.held)}
						{@const marked = row.kind === 'weight' ? row.flipped || row.drop : row.helps || (row.kind === 'family' && row.drop)}
						{@const perUserTone = row.kind === 'family' && row.perUser ? tone(row.perUser.gain, row.perUser.p) : undefined}
						<tr
							data-row={row.kind === 'weight' ? row.name : row.code}
							class="border-b border-border/50 tabular-nums
								{row.kind === 'family' ? 'font-medium' : ''}
								{held ? 'italic text-muted-foreground border-l-2 border-dashed border-l-muted-foreground/40' : 'text-card-foreground'}
								{marked ? 'bg-amber-500/15' : ''}"
						>
							<td class="py-1.5 pr-3 whitespace-nowrap {row.kind === 'family' ? `pt-3 ${held ? 'pl-3' : ''}` : held ? 'pl-7' : 'pl-4'}">
								{@render hint(row.info?.label ?? (row.kind === 'weight' ? row.name : row.code), row.info?.tip)}
								{#if held}<span class="ml-1 text-xs not-italic">· held out</span>{/if}
								{#if row.kind !== 'weight' && row.helps}<span class="ml-1 text-xs not-italic">★ would help now</span>{/if}
								{#if row.kind !== 'held' && row.drop}<span class="ml-1 text-xs not-italic">★ dropping it would help now</span>{/if}
								{#if row.kind === 'weight' && row.flipped}<span class="ml-1 text-xs">⚠ flipped</span>{/if}
							</td>
							<td class="py-1.5 pr-3">{row.kind === 'weight' ? fixed(row.live, 2) : ''}</td>
							<td class="py-1.5 pr-3">{row.kind === 'weight' ? fixed(row.refit, 2) : ''}</td>
							<td class="py-1.5 pr-3 {row.kind === 'weight' ? changeTone(row) : ''}">{row.kind === 'weight' ? signed(row.refit - (row.live ?? 0), 2) : ''}</td>
							<td class="py-1.5 pr-3 whitespace-nowrap">{bySplit(row.effect, (e) => signed(e.hit25))}</td>
							<td class="py-1.5 pr-3 whitespace-nowrap">
								{#each nllBySplit(row.effect) as cell, k (cell.key)}{k ? ' / ' : ''}<span data-tone={cell.tone} class={cell.tone ? TONE[cell.tone] : ''}>{cell.text}</span>{/each}
							</td>
							<td class="py-1.5 pr-3 whitespace-nowrap">{bySplit(row.effect, (e) => pValue(e.p))}</td>
							<td class="py-1.5 pr-3 whitespace-nowrap {row.kind === 'family' && row.perUser?.helps ? 'bg-amber-500/15' : ''} {perUserTone ? TONE[perUserTone] : ''}" data-per-user={row.kind === 'family' ? row.code : undefined}>
								{#if row.kind === 'family' && row.perUser}{signed(row.perUser.gain)} · p {pValue(row.perUser.p)}{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/snippet}
	{@render card(
		'Features',
		'The ranked weights by family, with what each family adds to the fit (by removing it), and in italics what the ranking leaves out (by adding it). Each pair of figures is time split / leave one user out.',
		body,
	)}
{/if}

{#if report?.rewatch}
	{#snippet body()}
		{#if rewatch.length}
			{@render table([['Test'], ['Picks'], ['Family top 10', METRIC_TIPS.hit10], ['Median place', METRIC_TIPS.median],
				['Own score top 10', METRIC_TIPS.hit10], ['Median place', METRIC_TIPS.median], ['p', METRIC_TIPS.p]], rewatch)}
		{:else}
			<p class="text-sm text-muted-foreground">No complete rewatch to measure.</p>
		{/if}
	{/snippet}
	{@render card(
		'Complete rewatches · held out',
		`${report.rewatch.decisions} rewatches of finished, unlisted anime, among ${report.rewatch.candidates_mean} each on average, against ranking by own score alone.`,
		body,
	)}
{/if}

{#if report?.online}
	{#snippet body()}
		{#if online.length}
			{@render table([['Reason'], ['Shown', METRIC_TIPS.shown], ['Picked'], ['Share', METRIC_TIPS.watched]], online)}
		{:else}
			<p class="text-sm text-muted-foreground">Nothing to judge yet.</p>
		{/if}
	{/snippet}
	{@render card(
		'The row, watched',
		`Of the anime shown in the Home row, the share picked within the user's next five picks, by the reason shown. ${report.online.waiting} still wait for those picks.`,
		body,
	)}
{/if}

{#if report?.watchlist}
	{@const g = report.watchlist}
	{#snippet body()}
		{#if watchlist.length}
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					{@render head([[''], ['Lift', METRIC_TIPS.lift], ['Picks', METRIC_TIPS.listPicks], ['Per 100 listed days', METRIC_TIPS.hazard],
						['Listed days', METRIC_TIPS.days]])}
					<tbody>
						{#each watchlist as w, i (i)}
							{#if i === 0 || watchlist[i - 1].group !== w.group}
								<tr><td colspan="5" class="pt-3 pb-1 text-xs uppercase tracking-wide text-muted-foreground">{w.group}</td></tr>
							{/if}
							<tr class="border-b border-border/50 tabular-nums text-card-foreground">
								<td class="py-1.5 pr-3 pl-4 whitespace-nowrap">{w.label}</td>
								<td class="py-1.5 pr-3">{w.lift == null ? '—' : `${fixed(w.lift, 2)}×`}</td>
								<td class="py-1.5 pr-3">{w.picks}</td>
								<td class="py-1.5 pr-3">{fixed(w.per100, 2)}</td>
								<td class="py-1.5 pr-3">{w.days ?? '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<p class="text-sm text-muted-foreground">No picks since the log began.</p>
		{/if}
	{/snippet}
	{@render card('Watchlist', `${g.picks} picks since the log began, ${pct(g.listed_share)} of them listed at the time. Over every user.`, body)}
{/if}

