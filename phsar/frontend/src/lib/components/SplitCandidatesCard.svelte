<script lang="ts">
    import { onMount } from 'svelte';
    import { api, ApiError } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import * as Card from '$lib/components/ui/card';
    import { Badge } from '$lib/components/ui/badge';
    import Tooltip from '$lib/components/Tooltip.svelte';
    import DismissedDecisionsSection from '$lib/components/admin/DismissedDecisionsSection.svelte';
    import { Split, X, RefreshCw, Search, ChevronRight, ChevronDown } from 'lucide-svelte';
    import { bumpCurationRefresh } from '$lib/stores/jobs';
    import { formatRelationType } from '$lib/utils/formatString';
    import type {
        SplitBackfillResult,
        SplitCandidateListItem,
        SplitResult,
    } from '$lib/types/api';

    let { currentUsername = '' }: { currentUsername?: string } = $props();

    let candidates = $state<SplitCandidateListItem[]>([]);
    // `loading` flips off after the first fetch and stays off; subsequent
    // fetches only toggle `refreshing`. Same silent-refresh pattern as
    // MergeCandidatesCard.
    let loading = $state(true);
    let refreshing = $state(false);
    let redetecting = $state(false);
    let busy = $derived(loading || refreshing || redetecting);
    let error = $state('');
    let info = $state('');
    let busyUuid = $state<string | null>(null);
    let confirmSplitUuid = $state<string | null>(null);
    let confirmDismissUuid = $state<string | null>(null);
    let expandedClusters = $state<Record<string, boolean>>({});

    onMount(async () => {
        await fetchCandidates();
        loading = false;
    });

    async function refreshCandidates() {
        info = '';
        await fetchCandidates();
    }

    async function fetchCandidates() {
        refreshing = true;
        error = '';
        try {
            candidates = await api.get<SplitCandidateListItem[]>('/admin/split-candidates');
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to load split candidates';
        } finally {
            refreshing = false;
        }
    }

    async function handleSplit(uuid: string) {
        busyUuid = uuid;
        error = '';
        info = '';
        try {
            const result = await api.post<SplitResult>(`/admin/split-candidates/${uuid}/split`, {});
            confirmSplitUuid = null;
            const count = result.new_anime_uuids.length;
            info = `Split succeeded — ${count} new anime row${count === 1 ? '' : 's'} created.`;
            // Refetch so the resolved row drops out and any post-split
            // detection (nested clusters, fresh merge candidates against
            // the new anime) lands on the next paint.
            await fetchCandidates();
            // A successful split also touches merge candidates (post-split
            // detection re-runs against the new anime), so bump curation
            // refresh — covers both surfaces in one signal.
            bumpCurationRefresh();
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to split';
        } finally {
            busyUuid = null;
        }
    }

    async function handleRedetect() {
        redetecting = true;
        error = '';
        info = '';
        try {
            const result = await api.post<SplitBackfillResult>('/admin/split-candidates/backfill', {});
            info = result.inserted === 0
                ? 'No new split candidates found.'
                : `Flagged ${result.inserted} new candidate${result.inserted === 1 ? '' : 's'}.`;
            await fetchCandidates();
            if (result.inserted > 0) bumpCurationRefresh();
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to re-run detection';
        } finally {
            redetecting = false;
        }
    }

    async function handleDismiss(uuid: string) {
        busyUuid = uuid;
        error = '';
        info = '';
        try {
            await api.post(`/admin/split-candidates/${uuid}/dismiss`, {});
            confirmDismissUuid = null;
            candidates = candidates.filter((c) => c.uuid !== uuid);
            bumpCurationRefresh();
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to dismiss';
        } finally {
            busyUuid = null;
        }
    }

    function sourceSummaryLine(c: SplitCandidateListItem): string {
        const a = c.source_anime;
        const parts: string[] = [];
        if (a.earliest_year !== null) parts.push(String(a.earliest_year));
        parts.push(`${a.media_count} media`);
        if (a.rating_count > 0) parts.push(`${a.rating_count} rating${a.rating_count === 1 ? '' : 's'}`);
        if (a.studios.length > 0) parts.push(a.studios.slice(0, 2).join(', '));
        return parts.join(' · ');
    }
</script>

<Card.Root>
    <Card.Header>
        <div class="flex items-center justify-between">
            <h2 class="text-lg font-semibold text-card-foreground">Split Candidates ({candidates.length})</h2>
            <div class="flex items-center gap-1">
                <Tooltip text="Re-run disjoint-franchise detection across the catalog">
                    {#snippet trigger(props)}
                        <Button
                            {...props}
                            variant="ghost"
                            size="sm"
                            onclick={handleRedetect}
                            disabled={busy}
                            aria-label="Re-run disjoint-franchise detection"
                        >
                            <Search class="size-4 {redetecting ? 'animate-pulse' : ''}" />
                        </Button>
                    {/snippet}
                </Tooltip>
                <Tooltip text="Refresh">
                    {#snippet trigger(props)}
                        <Button {...props} variant="ghost" size="sm" onclick={refreshCandidates} disabled={busy} aria-label="Refresh">
                            <RefreshCw class="size-4 {refreshing ? 'animate-spin' : ''}" />
                        </Button>
                    {/snippet}
                </Tooltip>
            </div>
        </div>
        <p class="text-xs text-muted-foreground">
            Anime that bundle disjoint sub-franchises (e.g. BNHA + Vigilante under one row). Splitting creates a fresh anime per cluster and re-parents the media — ratings stay attached to the same media.
        </p>
        {#if info}
            <p class="text-xs text-primary mt-1">{info}</p>
        {/if}
    </Card.Header>
    <Card.Content>
        {#if error}
            <p class="text-destructive text-sm mb-3">{error}</p>
        {/if}

        {#if loading}
            <p class="text-muted-foreground text-sm">Loading…</p>
        {:else if candidates.length === 0}
            <p class="text-muted-foreground text-sm">No pending split candidates.</p>
        {:else}
            <div class="space-y-3">
                {#each candidates as c (c.uuid)}
                    <div class="rounded-lg border bg-muted/30 px-4 py-3 space-y-3">
                        <div class="flex items-center gap-2 flex-wrap text-xs">
                            <Badge class="bg-primary/10 text-primary">
                                {c.clusters.length} cluster{c.clusters.length === 1 ? '' : 's'}
                            </Badge>
                            <span class="text-muted-foreground">{c.detected_by}</span>
                        </div>

                        <div class="rounded border bg-card px-3 py-2 space-y-1">
                            <div class="text-xs font-semibold uppercase text-muted-foreground tracking-wide">
                                Source anime (will lose extracted clusters)
                            </div>
                            <a
                                href="/anime?uuid={c.source_anime.uuid}"
                                class="text-sm font-medium text-card-foreground hover:text-primary transition block"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                {c.source_anime.title}
                            </a>
                            {#if c.source_anime.name_eng && c.source_anime.name_eng !== c.source_anime.title}
                                <p class="text-xs text-muted-foreground">{c.source_anime.name_eng}</p>
                            {/if}
                            <p class="text-xs text-muted-foreground">{sourceSummaryLine(c)}</p>
                        </div>

                        <div class="text-xs">
                            <button
                                type="button"
                                class="text-muted-foreground hover:text-primary transition flex items-center gap-1"
                                onclick={() => (expandedClusters[c.uuid] = !expandedClusters[c.uuid])}
                            >
                                {#if expandedClusters[c.uuid]}
                                    <ChevronDown class="size-3" />
                                {:else}
                                    <ChevronRight class="size-3" />
                                {/if}
                                <span>
                                    {c.clusters.reduce((acc, cl) => acc + cl.members.length, 0)} media across {c.clusters.length} new anime row{c.clusters.length === 1 ? '' : 's'}
                                </span>
                            </button>
                            {#if expandedClusters[c.uuid]}
                                <div class="mt-2 space-y-3">
                                    {#each c.clusters as cluster, ci (cluster.suggested_anchor_mal_id)}
                                        <div class="ml-4 rounded border bg-card/50 p-2">
                                            <div class="text-xs font-semibold text-card-foreground mb-1">
                                                Cluster #{ci + 1} — anchor mal_id={cluster.suggested_anchor_mal_id}
                                            </div>
                                            <ul class="space-y-0.5 text-muted-foreground">
                                                {#each cluster.members as m (m.media_uuid)}
                                                    <li class="flex items-baseline gap-2">
                                                        <span class="text-card-foreground">{m.title}</span>
                                                        <span class="text-xs">
                                                            {m.media_type} · {formatRelationType(m.relation_type)}
                                                        </span>
                                                    </li>
                                                {/each}
                                            </ul>
                                            {#if cluster.bridge_edges.length > 0}
                                                <div class="text-xs mt-2 text-muted-foreground">
                                                    Bridge edge{cluster.bridge_edges.length === 1 ? '' : 's'}:
                                                    {cluster.bridge_edges.map((e) => e[2]).join(', ')}
                                                </div>
                                            {:else}
                                                <div class="text-xs mt-2 text-muted-foreground italic">
                                                    No bridge edges — orphan via dropped/dangling MAL relations.
                                                </div>
                                            {/if}
                                        </div>
                                    {/each}
                                </div>
                            {/if}
                        </div>

                        <div class="flex justify-end gap-2 pt-1">
                            {#if confirmSplitUuid === c.uuid}
                                <Button variant="secondary" size="sm" onclick={() => (confirmSplitUuid = null)} disabled={busyUuid === c.uuid}>
                                    Cancel
                                </Button>
                                <Button size="sm" onclick={() => handleSplit(c.uuid)} disabled={busyUuid === c.uuid}>
                                    {busyUuid === c.uuid ? 'Splitting…' : 'Confirm split'}
                                </Button>
                            {:else if confirmDismissUuid === c.uuid}
                                <Button variant="secondary" size="sm" onclick={() => (confirmDismissUuid = null)} disabled={busyUuid === c.uuid}>
                                    Cancel
                                </Button>
                                <Button variant="destructive" size="sm" onclick={() => handleDismiss(c.uuid)} disabled={busyUuid === c.uuid}>
                                    {busyUuid === c.uuid ? 'Dismissing…' : 'Confirm dismiss'}
                                </Button>
                            {:else}
                                <Tooltip text="Dismiss — keep bundled">
                                    {#snippet trigger(props)}
                                        <Button {...props} variant="ghost" size="sm" onclick={() => (confirmDismissUuid = c.uuid)}>
                                            <X class="size-4 mr-1" /> Dismiss
                                        </Button>
                                    {/snippet}
                                </Tooltip>
                                <Tooltip text="Split clusters into separate anime">
                                    {#snippet trigger(props)}
                                        <Button {...props} size="sm" onclick={() => (confirmSplitUuid = c.uuid)}>
                                            <Split class="size-4 mr-1" /> Split
                                        </Button>
                                    {/snippet}
                                </Tooltip>
                            {/if}
                        </div>
                    </div>
                {/each}
            </div>
        {/if}

        <DismissedDecisionsSection
            kind="split"
            listUrl="/admin/split-candidates/dismissed"
            basePath="/admin/split-candidates"
            {currentUsername}
            onResurfaced={handleRedetect}
        >
            {#snippet row(item: SplitCandidateListItem)}
                <div class="text-sm font-medium text-card-foreground">{item.source_anime.title}</div>
                {#each item.clusters as cluster, i (i)}
                    <p class="text-[11px] text-muted-foreground">
                        <span class="text-card-foreground/70">would split off:</span>
                        {cluster.members.map((m) => m.title).join(', ') || '—'}
                    </p>
                {/each}
                <p class="text-[11px] text-muted-foreground/70">{item.detected_by}</p>
            {/snippet}
        </DismissedDecisionsSection>
    </Card.Content>
</Card.Root>
