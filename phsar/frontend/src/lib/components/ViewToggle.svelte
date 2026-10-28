<script lang="ts">
	// The Grid / Table pills of the ratings and watchlist lists — one component, so a fix
	// reaches both, as GrainToggle is for anime/media. Below 360px the icons drop, so the pills
	// and the grain toggle keep one line.
	import { LayoutGrid, Table as TableIcon } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';

	interface Props {
		view: 'grid' | 'table';
		onSelect: (view: 'grid' | 'table') => void;
	}

	let { view, onSelect }: Props = $props();

	const VIEWS = [
		{ value: 'grid' as const, label: 'Grid', icon: LayoutGrid },
		{ value: 'table' as const, label: 'Table', icon: TableIcon },
	];
</script>

{#each VIEWS as v (v.value)}
	<button
		type="button"
		aria-pressed={view === v.value}
		class="{cls.pagePill} inline-flex items-center gap-1.5 {view === v.value ? cls.pagePillOn : cls.pagePillOff}"
		onclick={() => onSelect(v.value)}
	>
		<v.icon class="size-3.5 max-xs:hidden" /> {v.label}
	</button>
{/each}
