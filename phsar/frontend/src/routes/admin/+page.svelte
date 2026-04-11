<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { api, ApiError } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Select from '$lib/components/ui/select';
	import { Label } from '$lib/components/ui/label';
	import { Badge } from '$lib/components/ui/badge';
	import { Copy, Trash2, Plus, ArrowUpDown } from 'lucide-svelte';
	import Toast from '$lib/components/Toast.svelte';
	import type { RegistrationTokenListItem } from '$lib/types/api';

	const getUserRole = getContext<() => string | null>('userRole');

	type SortOption = 'status' | 'newest' | 'expiring_soon' | 'recently_used';

	const SORT_OPTIONS: { value: SortOption; label: string }[] = [
		{ value: 'status', label: 'By Status' },
		{ value: 'newest', label: 'Newest First' },
		{ value: 'expiring_soon', label: 'Expiring Soon' },
		{ value: 'recently_used', label: 'Recently Used' },
	];

	const STATUS_ORDER: Record<string, number> = { active: 0, used: 1, expired: 2 };

	let tokens = $state<RegistrationTokenListItem[]>([]);
	let loading = $state(true);
	let error = $state('');
	let sortBy = $state<SortOption>('status');

	// Create form
	let createRole = $state<string>('user');
	let createExpiry = $state<string>('7');
	let creating = $state(false);

	let newTokenStr = $state<string | null>(null);
	let confirmDeleteUuid = $state<string | null>(null);
	let deleting = $state(false);
	let showToast = $state(false);
	let toastMessage = $state('');

	let sortedTokens = $derived.by(() => {
		const sorted = [...tokens];
		switch (sortBy) {
			case 'status':
				sorted.sort((a, b) => {
					const statusDiff = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
					if (statusDiff !== 0) return statusDiff;
					return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
				});
				break;
			case 'newest':
				sorted.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
				break;
			case 'expiring_soon': {
				// Active tokens sorted by expiry (soonest first), then the rest by creation date
				const active = sorted.filter(t => t.status === 'active');
				const rest = sorted.filter(t => t.status !== 'active');
				active.sort((a, b) => new Date(a.expires_on).getTime() - new Date(b.expires_on).getTime());
				rest.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
				return [...active, ...rest];
			}
			case 'recently_used': {
				// Used tokens sorted by used_at (newest first), then the rest by creation date
				const used = sorted.filter(t => t.used_at);
				const notUsed = sorted.filter(t => !t.used_at);
				used.sort((a, b) => new Date(b.used_at!).getTime() - new Date(a.used_at!).getTime());
				notUsed.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
				return [...used, ...notUsed];
			}
		}
		return sorted;
	});

	function toast(msg: string) {
		toastMessage = msg;
		showToast = true;
		setTimeout(() => (showToast = false), 2000);
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric',
			year: 'numeric',
		});
	}

	function truncateToken(t: string): string {
		return t.length > 16 ? `${t.slice(0, 8)}...${t.slice(-8)}` : t;
	}

	async function copyToClipboard(text: string) {
		await navigator.clipboard.writeText(text);
		toast('Copied to clipboard');
	}

	onMount(async () => {
		const role = getUserRole();
		if (role !== 'admin') {
			goto('/');
			return;
		}
		await fetchTokens();
	});

	async function fetchTokens() {
		loading = true;
		error = '';
		try {
			tokens = await api.get<RegistrationTokenListItem[]>('/admin/registration-tokens');
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to load tokens';
		} finally {
			loading = false;
		}
	}

	async function handleCreate() {
		creating = true;
		error = '';
		newTokenStr = null;
		try {
			const resp = await api.post<{ token: string }>('/admin/registration-tokens', {
				role: createRole,
				expires_in_days: parseInt(createExpiry),
			});
			newTokenStr = resp.token;
			await fetchTokens();
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to create token';
		} finally {
			creating = false;
		}
	}

	async function handleDelete(uuid: string) {
		deleting = true;
		error = '';
		try {
			await api.del(`/admin/registration-tokens/${uuid}`);
			confirmDeleteUuid = null;
			toast('Token deleted');
			await fetchTokens();
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to delete token';
		} finally {
			deleting = false;
		}
	}
</script>

<div class="mx-auto max-w-3xl space-y-6">
	<h1 class="text-2xl font-bold text-white">Admin</h1>

	{#if error}
		<p class="text-destructive text-sm">{error}</p>
	{/if}

	<Card.Root>
		<Card.Header>
			<h2 class="text-lg font-semibold text-card-foreground">Create Registration Token</h2>
		</Card.Header>
		<Card.Content class="space-y-4">
			<div class="flex items-end gap-4 flex-wrap">
				<div class="space-y-1">
					<Label>Role</Label>
					<Select.Root type="single" value={createRole} onValueChange={(v) => { if (v) { createRole = v; newTokenStr = null; } }}>
						<Select.Trigger class="w-44">{createRole === 'user' ? 'User' : 'Restricted User'}</Select.Trigger>
						<Select.Content>
							<Select.Item value="user">User</Select.Item>
							<Select.Item value="restricted_user">Restricted User</Select.Item>
						</Select.Content>
					</Select.Root>
				</div>
				<div class="space-y-1">
					<Label>Expires in</Label>
					<Select.Root type="single" value={createExpiry} onValueChange={(v) => { if (v) { createExpiry = v; newTokenStr = null; } }}>
						<Select.Trigger class="w-36">
							{createExpiry === '1' ? '1 day' : createExpiry === '7' ? '7 days' : '30 days'}
						</Select.Trigger>
						<Select.Content>
							<Select.Item value="1">1 day</Select.Item>
							<Select.Item value="7">7 days</Select.Item>
							<Select.Item value="30">30 days</Select.Item>
						</Select.Content>
					</Select.Root>
				</div>
				<Button onclick={handleCreate} disabled={creating}>
					<Plus class="size-4 mr-1" />
					{creating ? 'Creating...' : 'Create'}
				</Button>
			</div>

			{#if newTokenStr}
				<div class="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 space-y-2">
					<p class="text-sm font-medium text-card-foreground">Token created successfully</p>
					<div class="flex items-center gap-2">
						<code class="flex-1 text-sm bg-muted/50 px-3 py-1.5 rounded border text-card-foreground break-all select-all">{newTokenStr}</code>
						<Button
							size="sm"
							onclick={() => copyToClipboard(newTokenStr!)}
						>
							<Copy class="size-3.5 mr-1" />
							Copy
						</Button>
					</div>
				</div>
			{/if}
		</Card.Content>
	</Card.Root>

	<Card.Root>
		<Card.Header>
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-semibold text-card-foreground">Registration Tokens</h2>
				<div class="flex items-center gap-2">
					<ArrowUpDown class="size-4 text-muted-foreground" />
					<Select.Root type="single" value={sortBy} onValueChange={(v) => { if (v) sortBy = v as SortOption; }}>
						<Select.Trigger class="w-40 h-8 text-sm">
							{SORT_OPTIONS.find(o => o.value === sortBy)?.label}
						</Select.Trigger>
						<Select.Content>
							{#each SORT_OPTIONS as opt}
								<Select.Item value={opt.value}>{opt.label}</Select.Item>
							{/each}
						</Select.Content>
					</Select.Root>
				</div>
			</div>
		</Card.Header>
		<Card.Content>
			{#if loading}
				<p class="text-muted-foreground text-sm">Loading tokens...</p>
			{:else if sortedTokens.length === 0}
				<p class="text-muted-foreground text-sm">No registration tokens yet.</p>
			{:else}
				<div class="space-y-3">
					{#each sortedTokens as t (t.uuid)}
						<div class="flex items-center gap-3 rounded-lg border bg-muted/30 px-4 py-3 {t.status === 'expired' ? 'opacity-60' : ''}">
							<div class="flex-1 min-w-0 space-y-1">
								<div class="flex items-center gap-2 flex-wrap">
									<button
										class="flex items-center gap-1.5 text-sm text-card-foreground hover:text-primary transition cursor-pointer"
										title="Copy full token"
										onclick={() => copyToClipboard(t.token)}
									>
										<code>{truncateToken(t.token)}</code>
										<Copy class="size-3 shrink-0" />
									</button>
									{#if t.status === 'active'}
										<Badge>active</Badge>
									{:else if t.status === 'used'}
										<Badge class="bg-muted text-muted-foreground">used</Badge>
									{:else}
										<Badge class="bg-destructive/15 text-destructive">expired</Badge>
									{/if}
									<Badge class="bg-primary/10 text-primary">{t.role === 'user' ? 'User' : t.role === 'restricted_user' ? 'Restricted' : t.role}</Badge>
								</div>
								<div class="text-xs text-muted-foreground flex gap-3 flex-wrap">
									<span>Created {formatDate(t.created_at)} by {t.created_by}</span>
									<span>Expires {formatDate(t.expires_on)}</span>
									{#if t.used_by}
										<span>Used by <strong>{t.used_by}</strong></span>
									{/if}
								</div>
							</div>

							{#if t.status !== 'used'}
								<div class="shrink-0">
									{#if confirmDeleteUuid === t.uuid}
										<div class="flex gap-1.5">
											<Button variant="secondary" size="sm" onclick={() => (confirmDeleteUuid = null)} disabled={deleting}>
												Cancel
											</Button>
											<Button variant="destructive" size="sm" onclick={() => handleDelete(t.uuid)} disabled={deleting}>
												{deleting ? '...' : 'Confirm'}
											</Button>
										</div>
									{:else}
										<Button variant="ghost" size="sm" onclick={() => (confirmDeleteUuid = t.uuid)} title="Delete token">
											<Trash2 class="size-4 text-destructive" />
										</Button>
									{/if}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</Card.Content>
	</Card.Root>
</div>

<Toast message={toastMessage} show={showToast} />
