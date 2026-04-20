<script lang="ts">
    import { onMount } from 'svelte';
    import { api, ApiError } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import * as Card from '$lib/components/ui/card';
    import * as Select from '$lib/components/ui/select';
    import * as Dialog from '$lib/components/ui/dialog';
    import { Label } from '$lib/components/ui/label';
    import { Input } from '$lib/components/ui/input';
    import { Badge } from '$lib/components/ui/badge';
    import {
        ArrowUpDown,
        Download,
        GitBranch,
        Plus,
        RotateCcw,
        Trash2,
        Upload,
    } from 'lucide-svelte';
    import { formatBytes, formatShortDateTime } from '$lib/utils/formatString';
    import type { BackupMetadata, BackupSource } from '$lib/types/api';

    interface Props {
        currentUsername: string;
    }

    let { currentUsername }: Props = $props();

    type SortOption = 'newest' | 'oldest' | 'largest' | 'status';

    const SORT_OPTIONS: { value: SortOption; label: string }[] = [
        { value: 'newest', label: 'Newest first' },
        { value: 'oldest', label: 'Oldest first' },
        { value: 'largest', label: 'Largest first' },
        { value: 'status', label: 'By integrity' },
    ];

    const STATUS_ORDER: Record<string, number> = { corrupt: 0, unknown: 1, ok: 2 };

    const SOURCE_LABELS: Record<BackupSource, string> = {
        manual: 'Manual',
        cron: 'Scheduled',
        pre_restore: 'Pre-restore',
        upload: 'Upload',
    };

    const USERNAME_UNAVAILABLE_ERROR =
        'Your username is unavailable — please reload the page before restoring.';

    let backups = $state<BackupMetadata[]>([]);
    let loading = $state(true);
    let error = $state('');
    let sortBy = $state<SortOption>('newest');

    let creating = $state(false);
    let uploading = $state(false);
    let confirmDeleteFilename = $state<string | null>(null);
    let deleting = $state(false);

    let restoreFilename = $state<string | null>(null);
    let restoreConfirmInput = $state('');
    let restoring = $state(false);
    let restoreError = $state('');
    let restoreResultMessage = $state('');

    let fileInput: HTMLInputElement | null = $state(null);

    let sortedBackups = $derived.by(() => {
        const sorted = [...backups];
        switch (sortBy) {
            case 'newest':
                sorted.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
                break;
            case 'oldest':
                sorted.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
                break;
            case 'largest':
                sorted.sort((a, b) => b.size_bytes - a.size_bytes);
                break;
            case 'status':
                sorted.sort((a, b) => {
                    const diff = (STATUS_ORDER[a.integrity] ?? 9) - (STATUS_ORDER[b.integrity] ?? 9);
                    if (diff !== 0) return diff;
                    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
                });
                break;
        }
        return sorted;
    });

    export async function refresh() {
        loading = true;
        error = '';
        try {
            backups = await api.get<BackupMetadata[]>('/admin/backups');
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to load backups';
        } finally {
            loading = false;
        }
    }

    onMount(refresh);

    async function handleCreate() {
        creating = true;
        error = '';
        try {
            await api.post<BackupMetadata>('/admin/backups', {});
            await refresh();
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to create backup';
        } finally {
            creating = false;
        }
    }

    async function handleUpload(event: Event) {
        const target = event.target as HTMLInputElement;
        const file = target.files?.[0];
        if (!file) return;

        uploading = true;
        error = '';
        try {
            const formData = new FormData();
            formData.append('file', file);
            await api.postMultipart<BackupMetadata>('/admin/backups/upload', formData);
            await refresh();
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to upload backup';
        } finally {
            uploading = false;
            if (fileInput) fileInput.value = '';
        }
    }

    async function handleDelete(filename: string) {
        deleting = true;
        error = '';
        try {
            await api.del(`/admin/backups/${encodeURIComponent(filename)}`);
            confirmDeleteFilename = null;
            await refresh();
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to delete backup';
        } finally {
            deleting = false;
        }
    }

    async function handleDownload(filename: string) {
        error = '';
        try {
            await api.downloadBlob(`/admin/backups/${encodeURIComponent(filename)}`, filename);
        } catch (err) {
            error = err instanceof ApiError ? err.detail : 'Failed to download backup';
        }
    }

    function openRestore(filename: string) {
        restoreFilename = filename;
        restoreConfirmInput = '';
        restoreError = currentUsername ? '' : USERNAME_UNAVAILABLE_ERROR;
        restoreResultMessage = '';
    }

    async function handleRestore() {
        if (!restoreFilename) return;
        // Defense-in-depth: empty `currentUsername` would match an empty input
        // and silently authorize the destructive action if `disabled` is bypassed.
        if (!currentUsername) {
            restoreError = USERNAME_UNAVAILABLE_ERROR;
            return;
        }
        restoring = true;
        restoreError = '';
        try {
            const snapshot = await api.post<BackupMetadata>(
                `/admin/backups/${encodeURIComponent(restoreFilename)}/restore`,
                { confirm: restoreConfirmInput },
            );
            restoreResultMessage = `Restore complete. Pre-restore snapshot saved as ${snapshot.filename}.`;
            restoreFilename = null;
            await refresh();
        } catch (err) {
            restoreError = err instanceof ApiError ? err.detail : 'Failed to restore backup';
        } finally {
            restoring = false;
        }
    }
</script>

<Card.Root>
    <Card.Header>
        <div class="flex items-center justify-between flex-wrap gap-2">
            <h2 class="text-lg font-semibold text-card-foreground">Backups</h2>
            <div class="flex items-center gap-2">
                <Button size="sm" onclick={handleCreate} disabled={creating}>
                    <Plus class="size-4 mr-1" />
                    {creating ? 'Creating...' : 'Create backup'}
                </Button>
                <Button size="sm" variant="secondary" onclick={() => fileInput?.click()} disabled={uploading}>
                    <Upload class="size-4 mr-1" />
                    {uploading ? 'Uploading...' : 'Upload'}
                </Button>
                <input
                    type="file"
                    accept=".dump"
                    class="hidden"
                    bind:this={fileInput}
                    onchange={handleUpload}
                />
            </div>
        </div>
    </Card.Header>
    <Card.Content class="space-y-4">
        {#if error}
            <p class="text-destructive text-sm">{error}</p>
        {/if}
        {#if restoreResultMessage}
            <p class="text-primary text-sm">{restoreResultMessage}</p>
        {/if}

        <div class="flex items-center gap-2">
            <ArrowUpDown class="size-4 text-muted-foreground" />
            <Select.Root type="single" value={sortBy} onValueChange={(v) => { if (v) sortBy = v as SortOption; }}>
                <Select.Trigger class="w-44 h-8 text-sm">
                    {SORT_OPTIONS.find(o => o.value === sortBy)?.label}
                </Select.Trigger>
                <Select.Content>
                    {#each SORT_OPTIONS as opt}
                        <Select.Item value={opt.value}>{opt.label}</Select.Item>
                    {/each}
                </Select.Content>
            </Select.Root>
        </div>

        {#if loading}
            <p class="text-muted-foreground text-sm">Loading backups...</p>
        {:else if sortedBackups.length === 0}
            <p class="text-muted-foreground text-sm">No backups yet.</p>
        {:else}
            <div class="space-y-3">
                {#each sortedBackups as b (b.filename)}
                    <div class="flex items-center gap-3 rounded-lg border px-4 py-3 {b.is_current ? 'border-blue-500/50 bg-blue-500/5' : 'bg-muted/30'}">
                        <div class="flex-1 min-w-0 space-y-1">
                            <div class="flex items-center gap-2 flex-wrap">
                                <code class="text-sm text-card-foreground break-all">{b.filename}</code>
                                {#if b.is_current}
                                    <Badge class="bg-blue-500/15 text-blue-400">
                                        <GitBranch class="size-3 mr-1" />
                                        Current
                                    </Badge>
                                {/if}
                                {#if b.integrity === 'ok'}
                                    <Badge>ok</Badge>
                                {:else if b.integrity === 'corrupt'}
                                    <Badge class="bg-destructive/15 text-destructive">corrupt</Badge>
                                {:else}
                                    <Badge class="bg-muted text-muted-foreground">unknown</Badge>
                                {/if}
                                <Badge class="bg-primary/10 text-primary">{SOURCE_LABELS[b.source]}</Badge>
                            </div>
                            <div class="text-xs text-muted-foreground flex gap-3 flex-wrap">
                                <span>Created {formatShortDateTime(b.created_at)}</span>
                                <span>{formatBytes(b.size_bytes)}</span>
                            </div>
                        </div>
                        <div class="shrink-0 flex gap-1">
                            <Button variant="ghost" size="sm" onclick={() => handleDownload(b.filename)} title="Download">
                                <Download class="size-4" />
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                onclick={() => openRestore(b.filename)}
                                title="Restore from this backup"
                                disabled={b.integrity === 'corrupt'}
                            >
                                <RotateCcw class="size-4 text-destructive" />
                            </Button>
                            {#if confirmDeleteFilename === b.filename}
                                <div class="flex gap-1.5">
                                    <Button variant="secondary" size="sm" onclick={() => (confirmDeleteFilename = null)} disabled={deleting}>
                                        Cancel
                                    </Button>
                                    <Button variant="destructive" size="sm" onclick={() => handleDelete(b.filename)} disabled={deleting}>
                                        {deleting ? '...' : 'Confirm'}
                                    </Button>
                                </div>
                            {:else}
                                <Button variant="ghost" size="sm" onclick={() => (confirmDeleteFilename = b.filename)} title="Delete backup">
                                    <Trash2 class="size-4 text-destructive" />
                                </Button>
                            {/if}
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </Card.Content>
</Card.Root>

<Dialog.Root open={restoreFilename !== null} onOpenChange={(open) => { if (!open) restoreFilename = null; }}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title class="text-destructive">Restore from backup</Dialog.Title>
            <Dialog.Description>
                This will replace the current database with the contents of
                <code class="break-all">{restoreFilename ?? ''}</code>. A pre-restore snapshot will be
                taken automatically. To confirm, type your admin username
                (<strong>{currentUsername}</strong>) below.
            </Dialog.Description>
        </Dialog.Header>
        <div class="space-y-4 py-2">
            <div class="space-y-2">
                <Label for="restore-confirm">Your username</Label>
                <Input
                    id="restore-confirm"
                    bind:value={restoreConfirmInput}
                    placeholder={currentUsername}
                    disabled={!currentUsername}
                    onkeydown={(e: KeyboardEvent) => {
                        if (
                            e.key === 'Enter'
                            && !!currentUsername
                            && restoreConfirmInput === currentUsername
                            && !restoring
                        ) handleRestore();
                    }}
                />
            </div>
            {#if restoreError}
                <p class="text-destructive text-sm">{restoreError}</p>
            {/if}
        </div>
        <Dialog.Footer>
            <Button variant="secondary" onclick={() => (restoreFilename = null)} disabled={restoring}>
                Cancel
            </Button>
            <Button
                variant="destructive"
                onclick={handleRestore}
                disabled={restoring || !currentUsername || restoreConfirmInput !== currentUsername}
            >
                {restoring ? 'Restoring...' : 'Restore now'}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
