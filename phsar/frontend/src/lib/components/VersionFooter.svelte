<script lang="ts">
  // Runtime env so svelte-kit sync works without the var set locally.
  import { env } from '$env/dynamic/public';

  const version = env.PUBLIC_APP_VERSION || 'dev';
  const hasReleaseTag = /^v\d/.test(version);
  const releaseUrl = `https://github.com/Priapos1004/phsar/releases/tag/${version}`;
</script>

<footer class="py-4 text-center text-xs text-muted-foreground">
  {#if hasReleaseTag}
    <a
      href={releaseUrl}
      target="_blank"
      rel="noopener noreferrer"
      class="hover:underline"
    >
      {version}
    </a>
  {:else}
    <span>{version}</span>
  {/if}
</footer>
