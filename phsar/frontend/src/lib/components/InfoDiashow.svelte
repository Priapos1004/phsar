<script lang="ts">
	import { getCurrentSeason } from '$lib/utils/getSeason';
	import { userSettings } from '$lib/stores/userSettings';
	import { getThemePic, getThemeFocal } from '$lib/themes';

	const currentSeason = getCurrentSeason();
	let themeKey = $derived($userSettings?.theme ?? 'default');
	let pic = $derived(getThemePic(themeKey));
	let focal = $derived(getThemeFocal(themeKey));
</script>

<div class="relative w-full overflow-hidden rounded-xl">
	<!-- Character background — transparent images scale to height, pinned right -->
	<img src={pic} alt="" class="h-64 sm:h-80 w-full object-cover" style="object-position: 50% {focal}" />

	<!-- Diagonal gradient overlay from primary color -->
	<div class="absolute inset-0 bg-gradient-to-r from-[var(--primary)] from-30% via-[var(--primary)]/60 to-transparent">
		<div class="flex flex-col justify-end h-full pl-8 pb-6 pr-4">
			<p class="text-xs sm:text-sm uppercase tracking-[0.25em] text-white/60 font-medium">Current Season</p>
			<p class="text-4xl sm:text-5xl font-extrabold text-white leading-none -skew-x-2"
				style="text-shadow: 0 0 40px var(--primary), 0 0 80px var(--primary), 0 2px 4px rgba(0,0,0,0.4)"
			>{currentSeason}</p>
		</div>
	</div>
</div>
