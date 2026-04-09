---
tags: [echarts, charting, svelte, vite, ssr, frontend]
category: feature
---

# ECharts Integration in SvelteKit + Svelte 5

**Date:** 2026-04-06 | **Branch:** v0.11.0-anime-search-pages

## Summary

Added ECharts for the anime detail ratings overview (gauge, bar chart, radar chart). The integration required navigating SSR incompatibility, Vite module resolution conflicts, and ECharts v6 breaking changes to arrive at a working lazy-loaded setup.

## Failed Approaches

- **ECharts v6 modular imports** (`echarts/core`, `echarts/charts`, etc.): v6's tree-shaken ESM modules use `import { __extends } from "tslib"`. Vite's `resolve.conditions: ['browser']` (required for Svelte 5 component resolution) causes tslib to resolve to a wrong entry point, producing `__extends is not a function`. Downgrading to v5 with the same modular imports hit the **exact same error** because the cached Vite pre-bundle from v6 persisted. Never do: assume `npm install` + restart clears Vite's module cache — you must also `rm -rf node_modules/.vite`.
- **ECharts v5 modular imports** (`echarts/core` + `echarts/charts`): Even after cache clearing, the modular imports still failed with `__extends` errors. The root cause is tslib ESM resolution under Vite's `browser` condition, not the ECharts version. Never do: use `echarts/core` + `echarts/charts` split imports in a Vite project with `resolve.conditions: ['browser']`.
- **Synchronous top-level import** (`import * as echarts from 'echarts/core'`): Crashes SSR because ECharts accesses DOM globals (`window`, `document`) at import time. Never do: statically import echarts in a SvelteKit project — it must be dynamically imported inside browser-only code.
- **Tailwind classes for chart container sizing** (`class="w-24 h-24"`): ECharts reads `offsetWidth`/`offsetHeight` at `init()` time. When the container gets dimensions from Tailwind classes applied asynchronously, ECharts sees 0×0 and renders nothing. Never do: rely on CSS classes for ECharts container dimensions — use inline `style` with explicit px values.

## Key Decisions

- **Pre-built ESM bundle** (`echarts/dist/echarts.esm.js`): This self-contained file has all tslib helpers inlined, bypassing the module resolution issue entirely. Trade-off: no tree-shaking (~800KB), but it actually works. Accepted because charts are a core feature going forward.
- **Lazy import via singleton**: `getEcharts()` returns a cached promise, called inside `onMount`. SSR-safe, loads once regardless of chart count.
- **`chart` as `$state`**: Making the ECharts instance reactive lets `$effect` naturally fire when chart transitions from null → instance after async init, applying the initial option without a separate `setOption` call in `onMount`.
- **ECharts v5.6.0 over v6.0.0**: v6 has fundamental ESM/tslib breakage in Vite. v5 is stable and the pre-built bundle works cleanly.

## Gotchas & Learnings

- Vite's `resolve.conditions: ['browser']` affects **all** dependencies, not just Svelte components. Any dep relying on tslib ESM can break.
- `@ts-expect-error` is needed on the `echarts/dist/echarts.esm.js` import — no `.d.ts` exists for the pre-built bundle. Types come from the top-level `echarts` package which is still installed.
- ECharts' default `emphasis` effect (highlight on hover) causes a blink-and-disappear visual artifact in Svelte's reactive context. Fix: `emphasis: { disabled: true }` on all series.
- Radar chart data items need an explicit `name` property, otherwise the tooltip shows "series0".

## Future Work

- Revisit ECharts v6 modular imports if Vite adds a way to exclude specific deps from `resolve.conditions`
- Chart theme colors are duplicated between `app.css` (`--color-chart-*`) and `chartColors.ts` — unavoidable since ECharts can't read CSS custom properties
