<script lang="ts">
	// The sort menu and its direction arrow, over any search's params: the search page and
	// the see-all pages. The caller applies the change — a new token, or a stored choice.
	import Tooltip from '$lib/components/Tooltip.svelte';
	import * as Select from '$lib/components/ui/select';
	import { ArrowDown, ArrowUp } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';
	import { effectiveSort, offeredSorts, type MediaSearchFilters, type SortDir, type SortKey } from '$lib/utils/search';

	interface Props {
		params: MediaSearchFilters;
		isGuest: boolean;
		/** A new key comes without a direction, so it starts at its own default. */
		onChange: (change: { sort: SortKey; sort_dir?: SortDir }) => void;
	}

	let { params, isGuest, onChange }: Props = $props();

	let order = $derived(effectiveSort(params));
	let sortOptions = $derived(offeredSorts(params));

	function flipDirection() {
		if (order.dir) onChange({ sort: order.sort, sort_dir: order.dir === 'asc' ? 'desc' : 'asc' });
	}
</script>

<Select.Root type="single" value={order.sort} onValueChange={(v) => v && v !== order.sort && onChange({ sort: v as SortKey })}>
	<Select.Trigger size="sm" class={cls.pageControl} aria-label="Sort by">
		{order.option.label}
	</Select.Trigger>
	<!-- Each option says what it orders by in place, rather than in a hover tooltip,
	     which neither touch nor arrow-key navigation would ever show. -->
	<Select.Content class="w-80">
		{#each sortOptions as opt (opt.value)}
			{@const guestOnly = opt.value === 'your_rating' && isGuest}
			<Select.Item value={opt.value} label={opt.label} disabled={guestOnly}>
				<div class="flex flex-col">
					<span>{opt.label}</span>
					<span class="text-xs text-muted-foreground">
						{guestOnly ? 'Guest accounts have no ratings to sort by' : opt.hint}
					</span>
				</div>
			</Select.Item>
		{/each}
	</Select.Content>
</Select.Root>
<Tooltip text={order.option.dir && order.dir ? `${order.option.dir[order.dir]} (click to reverse)` : `${order.option.label} has no direction`}>
	{#snippet trigger(props)}
		<button
			{...props}
			type="button"
			class="size-8 flex items-center justify-center {cls.pageControl} disabled:opacity-40 disabled:hover:text-white/80"
			aria-label="Reverse the order"
			disabled={!order.dir}
			onclick={flipDirection}
		>
			{#if order.dir === 'asc'}<ArrowUp class="size-4" />{:else}<ArrowDown class="size-4" />{/if}
		</button>
	{/snippet}
</Tooltip>
