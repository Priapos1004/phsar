<script lang="ts">
	import { formatNumber } from '$lib/utils/formatString';
	import { Bookmark } from 'lucide-svelte';
    import * as cls from '$lib/styles/classes';

    export let info_type: string; // "anime" or "media"
	export let title: string;
	export let score: number | null = null;
	export let scoredBy: number | null = null;
	export let anime_season: string | null = null;
    export let airing_status: string;
	export let genres: string[] | null = null;
    export let media_type: string;
    export let relation_type: string;
	export let watchtime: string | null = null;
	export let imageUrl: string | null = null;
	export let on_watchlist: boolean;
	export let media_uuid: string;
</script>

<a
	href={`/${info_type}?uuid=${media_uuid}`}
	class="block transition duration-200 transform hover:scale-[1.015]"
>
	<div class="flex gap-4 bg-white/80 backdrop-blur rounded-xl p-4 shadow-md">
		<!-- Cover Image -->
		{#if imageUrl}
			<img src={imageUrl} alt={`Cover of ${title}`} class="w-24 h-36 object-cover rounded-lg shadow-sm" />
		{:else}
			<div class="w-24 h-36 bg-gray-200 rounded-lg flex items-center justify-center text-gray-400 text-sm italic">
				No image
			</div>
		{/if}

		<!-- Right Content -->
		<div class="flex flex-col justify-between flex-grow space-y-2">
			<!-- Title + season + airing + bookmark -->
			<div class="flex items-start justify-between">
                <div>
                    <h3 class="text-lg font-bold text-gray-800">{title}</h3>
                    {#if anime_season || airing_status === 'Not yet aired' || airing_status === 'Currently Airing'}
                        <p class="text-sm text-purple-700">
                            {#if anime_season}
                                {anime_season}
                            {/if}
                            {#if airing_status === 'Not yet aired' || airing_status === 'Currently Airing'}
                                <span class="ml-2 text-xs text-purple-500">({airing_status})</span>
                            {/if}
                        </p>
                    {/if}
                </div>
                {#if on_watchlist}
                    <Bookmark class="w-5 h-5 text-purple-500" fill="currentColor" />
                {/if}
            </div>

			<!-- Genre Tags -->
			{#if media_type || relation_type || genres?.length}
                <div class="flex flex-wrap gap-2">
                    {#if media_type}
                        <span class={`${cls.tagBase} ${cls.tagMediaType}`}>{media_type}</span>
                    {/if}

                    {#if relation_type}
                        <span class={`${cls.tagBase} ${cls.tagRelation}`}>{relation_type}</span>
                    {/if}

                    {#each genres ?? [] as genre}
                        <span class={`${cls.tagBase} ${cls.tagGenre}`}>{genre}</span>
                    {/each}
                </div>
            {/if}

			<!-- Stats -->
			<div class="flex justify-between text-xs text-gray-600">
				<span>{watchtime ? `Watch time: ${watchtime}` : 'Watch time: N/A'}</span>
				{#if score !== null && scoredBy !== null}
					<span>⭐ {score} — {formatNumber(scoredBy)} users</span>
				{:else}
					<span>No rating</span>
				{/if}
			</div>
		</div>
	</div>
</a>
