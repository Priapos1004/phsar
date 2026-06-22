<!-- Shared opt-in toggle for erasing watch history alongside a rating delete/downgrade.
     The count sentence (`detail`) varies per caller; the label + standing explanation live here
     so the user-facing copy can't drift between the single-rating and bulk-delete dialogs. -->
<script lang="ts">
	import { Checkbox } from '$lib/components/ui/checkbox';

	interface Props {
		checked: boolean;
		/** Leading sentence describing how much history is at stake, e.g. "You have 2 recorded watches." */
		detail: string;
	}

	let { checked = $bindable(), detail }: Props = $props();
</script>

<label class="flex items-start gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm cursor-pointer">
	<Checkbox
		class="mt-0.5"
		{checked}
		onCheckedChange={(val: boolean | 'indeterminate') => { checked = val === true; }}
	/>
	<span>
		<span class="font-medium text-card-foreground">Also delete watch history</span>
		<span class="block text-muted-foreground">
			{detail} Kept by default — re-rating later keeps your watch dates. Check this to erase them permanently.
		</span>
	</span>
</label>
