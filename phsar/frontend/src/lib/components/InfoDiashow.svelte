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

	<!-- Bottom-up dark scrim purely for text legibility — no color cast over
	     the character art (replaces the old left primary-color overlay). -->
	<div class="absolute inset-0 bg-gradient-to-t from-black/65 via-black/20 to-transparent">
		<div class="flex flex-col justify-end h-full pl-8 pb-6 pr-4">
			<p class="text-xs sm:text-sm uppercase tracking-[0.25em] text-white/70 font-medium">Current Season</p>
			<p class="text-4xl sm:text-5xl font-extrabold text-white leading-none -skew-x-2"
				style="text-shadow: 0 2px 8px rgba(0,0,0,0.6)"
			>{currentSeason}</p>
		</div>
	</div>
</div>
