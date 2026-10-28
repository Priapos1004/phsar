<script lang="ts">
	// A filter chip's text, or the sheet's Reads line, in groups and terms — a genre
	// expression (`describeGenreTerms`) or a single run. It breaks between its groups first:
	// every group after the first is an inline-block, so a line wraps inside a group only when
	// that group alone is wider than it, and the first flows on from whatever label precedes
	// it. Inside a line, a `whole` term — one value — is an inline-block too, so a line breaks
	// between values before it breaks inside one. `keywordClass` sets apart the words a genre
	// expression is built from. The Reads line colours them; a chip leaves them plain, its text
	// already the theme colour and its capital AND / OR already apart.
	import type { Term } from '$lib/utils/search';

	let { parts, keywordClass = '' }: { parts: Term[][]; keywordClass?: string } = $props();
</script>

{#each parts as part, at (at)}{at ? ' ' : ''}<span class:inline-block={at}>{#each part as term, i (i)}{#if term.keyword}<span class={keywordClass}>{term.text}</span>{:else if term.whole}<span class="inline-block">{term.text}</span>{:else}{term.text}{/if}{/each}</span>{/each}
