<script lang="ts">
    import { onMount } from 'svelte';
    import { api, ApiError } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import * as Card from '$lib/components/ui/card';
    import { Badge } from '$lib/components/ui/badge';
    import { GitMerge, X, RefreshCw, ArrowLeftRight, Search } from 'lucide-svelte';
    import type {
        MergeBackfillResult,
        MergeCandidateAnimeSummary,
        MergeCandidateListItem,
    } from '$lib/types/api';

    let candidates = $state<MergeCandidateListItem[]>([]);
    // `loading` flips off after the first fetch and stays off; subsequent
    // fetches only toggle `refreshing`. That keeps the keyed each-block
    // mounted across refreshes so Svelte diffs the list in place — no full
    // unmount, no scroll jump.
    let loading = $state(true);
    let refreshing = $state(false);
    let redetecting = $state(false);
    let busy = $derived(loading || refreshing || redetecting);
    let error = $state('');
    let info = $state('');
    let busyUuid = $state<string | null>(null);
    let confirmMergeUuid = $state<string | null>(null);
    let confirmDismissUuid = $state<string | null>(null);
    // Per-candidate flip state. Keys are candidate uuids; flipping reorders
    // which side is rendered as A vs B and changes the keep_uuid sent on
    // merge — the backend ordering is just a recommendation.
    let swapped = $state<Record<string, boolean>>({});

    onMount(async () => {
        await fetchCandidates();
        loading = false;
    });

    function sides(c: MergeCandidateListItem): [MergeCandidateAnimeSummary, MergeCandidateAnimeSummary] {
        return swapped[c.uuid] ? [c.anime_b, c.anime_a] : [c.anime_a, c.anime_b];
    }

    async function refreshCandidates() {
        // Manual user-initiated refresh — clear the stale re-detect summary
        // so it doesn't outlive the run that produced it.
        info = '';
        await fetchCandidates();
    }

    async function fetchCandidates() {
        refreshing = true;
        error = '';
        try {
            candidates = await api.get<MergeCandidateListItem[]>('/admin/merge-candidates');
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to load merge candidates';
        } finally {
            refreshing = false;
        }
    }

    async function handleMerge(uuid: string) {
        const candidate = candidates.find((c) => c.uuid === uuid);
        if (!candidate) return;
        const [keep] = sides(candidate);
        busyUuid = uuid;
        error = '';
        info = '';
        try {
            await api.post(`/admin/merge-candidates/${uuid}/merge`, { keep_uuid: keep.uuid });
            confirmMergeUuid = null;
            // Refetch so the keyed each-block diffs in place: the merged row
            // drops out, any cascade-resolved candidates drop with it, and
            // re-detection may surface fresh pairs against the survivor.
            await fetchCandidates();
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to merge';
        } finally {
            busyUuid = null;
        }
    }

    async function handleRedetect() {
        redetecting = true;
        error = '';
        info = '';
        try {
            const result = await api.post<MergeBackfillResult>('/admin/merge-candidates/backfill', {});
            info = result.inserted === 0
                ? 'No new candidates found.'
                : `Flagged ${result.inserted} new candidate${result.inserted === 1 ? '' : 's'}.`;
            await fetchCandidates();
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
            await api.post(`/admin/merge-candidates/${uuid}/dismiss`, {});
            confirmDismissUuid = null;
            candidates = candidates.filter((c) => c.uuid !== uuid);
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to dismiss';
        } finally {
            busyUuid = null;
        }
    }

    function summaryLine(a: MergeCandidateAnimeSummary): string {
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
            <h2 class="text-lg font-semibold text-card-foreground">Merge Candidates</h2>
            <div class="flex items-center gap-1">
                <Button
                    variant="ghost"
                    size="sm"
                    onclick={handleRedetect}
                    disabled={busy}
                    title="Re-run detection across the existing catalog (useful after restoring a backup)"
                >
                    <Search class="size-4 {redetecting ? 'animate-pulse' : ''}" />
                </Button>
                <Button variant="ghost" size="sm" onclick={refreshCandidates} disabled={busy} title="Refresh">
                    <RefreshCw class="size-4 {refreshing ? 'animate-spin' : ''}" />
                </Button>
            </div>
        </div>
        <p class="text-xs text-muted-foreground">
            Pairs flagged by the duplicate detector. Merging re-parents B's media onto A and deletes B.
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
            <p class="text-muted-foreground text-sm">No pending merge candidates.</p>
        {:else}
            <div class="space-y-3">
                {#each candidates as c (c.uuid)}
                    <div class="rounded-lg border bg-muted/30 px-4 py-3 space-y-3">
                        <div class="flex items-center gap-2 flex-wrap text-xs">
                            <Badge class="bg-primary/10 text-primary">
                                {(c.similarity_score * 100).toFixed(0)}% match
                            </Badge>
                            <span class="text-muted-foreground">{c.detected_by}</span>
                            <Button
                                variant="ghost"
                                size="sm"
                                class="h-6 px-2 text-xs ml-auto"
                                onclick={() => (swapped[c.uuid] = !swapped[c.uuid])}
                                title="Swap A/B"
                            >
                                <ArrowLeftRight class="size-3 mr-1" /> Swap
                            </Button>
                        </div>

                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {#each sides(c) as anime, i (anime.uuid)}
                                <div class="rounded border bg-card px-3 py-2 space-y-1">
                                    <div class="text-xs font-semibold uppercase text-muted-foreground tracking-wide">
                                        Anime {i === 0 ? 'A (kept)' : 'B (merged in)'}
                                    </div>
                                    <a
                                        href="/anime?uuid={anime.uuid}"
                                        class="text-sm font-medium text-card-foreground hover:text-primary transition block"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                    >
                                        {anime.title}
                                    </a>
                                    {#if anime.name_eng && anime.name_eng !== anime.title}
                                        <p class="text-xs text-muted-foreground">{anime.name_eng}</p>
                                    {/if}
                                    <p class="text-xs text-muted-foreground">{summaryLine(anime)}</p>
                                </div>
                            {/each}
                        </div>

                        <div class="flex justify-end gap-2 pt-1">
                            {#if confirmMergeUuid === c.uuid}
                                <Button variant="secondary" size="sm" onclick={() => (confirmMergeUuid = null)} disabled={busyUuid === c.uuid}>
                                    Cancel
                                </Button>
                                <Button size="sm" onclick={() => handleMerge(c.uuid)} disabled={busyUuid === c.uuid}>
                                    {busyUuid === c.uuid ? 'Merging…' : 'Confirm merge'}
                                </Button>
                            {:else if confirmDismissUuid === c.uuid}
                                <Button variant="secondary" size="sm" onclick={() => (confirmDismissUuid = null)} disabled={busyUuid === c.uuid}>
                                    Cancel
                                </Button>
                                <Button variant="destructive" size="sm" onclick={() => handleDismiss(c.uuid)} disabled={busyUuid === c.uuid}>
                                    {busyUuid === c.uuid ? 'Dismissing…' : 'Confirm dismiss'}
                                </Button>
                            {:else}
                                <Button variant="ghost" size="sm" onclick={() => (confirmDismissUuid = c.uuid)} title="Dismiss — not a duplicate">
                                    <X class="size-4 mr-1" /> Dismiss
                                </Button>
                                <Button size="sm" onclick={() => (confirmMergeUuid = c.uuid)} title="Merge B into A">
                                    <GitMerge class="size-4 mr-1" /> Merge
                                </Button>
                            {/if}
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </Card.Content>
</Card.Root>
