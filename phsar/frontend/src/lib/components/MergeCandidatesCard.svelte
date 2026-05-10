<script lang="ts">
    import { onMount } from 'svelte';
    import { api, ApiError } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import * as Card from '$lib/components/ui/card';
    import { Badge } from '$lib/components/ui/badge';
    import { GitMerge, X, RefreshCw } from 'lucide-svelte';
    import type { MergeCandidateListItem, MergeCandidateAnimeSummary } from '$lib/types/api';

    let candidates = $state<MergeCandidateListItem[]>([]);
    let loading = $state(true);
    let error = $state('');
    let busyUuid = $state<string | null>(null);
    let confirmMergeUuid = $state<string | null>(null);
    let confirmDismissUuid = $state<string | null>(null);

    onMount(() => {
        fetchCandidates();
    });

    async function fetchCandidates() {
        loading = true;
        error = '';
        try {
            candidates = await api.get<MergeCandidateListItem[]>('/admin/merge-candidates');
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to load merge candidates';
        } finally {
            loading = false;
        }
    }

    async function handleMerge(uuid: string) {
        busyUuid = uuid;
        error = '';
        try {
            await api.post(`/admin/merge-candidates/${uuid}/merge`, {});
            confirmMergeUuid = null;
            candidates = candidates.filter((c) => c.uuid !== uuid);
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to merge';
        } finally {
            busyUuid = null;
        }
    }

    async function handleDismiss(uuid: string) {
        busyUuid = uuid;
        error = '';
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
        if (a.studios.length > 0) parts.push(a.studios.slice(0, 2).join(', '));
        return parts.join(' · ');
    }
</script>

<Card.Root>
    <Card.Header>
        <div class="flex items-center justify-between">
            <h2 class="text-lg font-semibold text-card-foreground">Merge Candidates</h2>
            <Button variant="ghost" size="sm" onclick={fetchCandidates} disabled={loading} title="Refresh">
                <RefreshCw class="size-4 {loading ? 'animate-spin' : ''}" />
            </Button>
        </div>
        <p class="text-xs text-muted-foreground">
            Pairs flagged by the duplicate detector. Merging re-parents B's media onto A and deletes B.
        </p>
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
                        </div>

                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {#each [c.anime_a, c.anime_b] as anime, i (anime.uuid)}
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
