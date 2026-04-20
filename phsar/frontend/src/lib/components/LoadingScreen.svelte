<script lang="ts"></script>

<!--
  Theme-aware sakura petal ring. 8 petals circle a soft glow; each flutters
  (scale + opacity) with a staggered delay while the whole ring rotates.
  Uses `var(--primary)` so the ring follows the active theme color.
-->
<div class="loading-wrapper" role="status" aria-label="Loading">
    <div class="ring">
        {#each Array(8) as _, i}
            <div class="petal-slot" style="--angle: {i * 45}deg">
                <div class="petal" style="--delay: {-i * 200}ms">
                    <svg viewBox="0 0 24 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                        <path
                            d="M12 2 Q 10 0 8 4 Q 2 14 4 28 Q 8 38 12 40 Q 16 38 20 28 Q 22 14 16 4 Q 14 0 12 2 Z"
                            fill="currentColor"
                        />
                    </svg>
                </div>
            </div>
        {/each}
        <div class="core" aria-hidden="true"></div>
    </div>
    <span class="sr-only">Loading</span>
</div>

<style>
    .loading-wrapper {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        color: var(--primary);
    }

    .ring {
        position: relative;
        width: 12rem;
        height: 12rem;
        animation: spin 6s linear infinite;
    }

    .petal-slot {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: flex-start;
        justify-content: center;
        transform: rotate(var(--angle));
    }

    .petal {
        width: 1.5rem;
        height: 2.5rem;
        margin-top: 0.25rem;
        color: var(--primary);
        transform-origin: center bottom;
        animation: flutter 1.8s ease-in-out infinite;
        animation-delay: var(--delay);
        filter: drop-shadow(0 0 6px color-mix(in oklab, var(--primary) 40%, transparent));
    }

    .petal svg {
        width: 100%;
        height: 100%;
        display: block;
    }

    .core {
        position: absolute;
        top: 50%;
        left: 50%;
        width: 3.5rem;
        height: 3.5rem;
        transform: translate(-50%, -50%);
        border-radius: 9999px;
        background: radial-gradient(
            circle,
            color-mix(in oklab, var(--primary) 35%, transparent) 0%,
            transparent 70%
        );
        animation: pulse 2.4s ease-in-out infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }

    @keyframes flutter {
        0%,
        100% {
            opacity: 0.35;
            transform: scale(0.85) translateY(0);
        }
        50% {
            opacity: 1;
            transform: scale(1.1) translateY(-4px);
        }
    }

    @keyframes pulse {
        0%,
        100% {
            opacity: 0.6;
            transform: translate(-50%, -50%) scale(0.9);
        }
        50% {
            opacity: 1;
            transform: translate(-50%, -50%) scale(1.15);
        }
    }

    .sr-only {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
    }

    @media (prefers-reduced-motion: reduce) {
        .ring,
        .petal,
        .core {
            animation: none;
        }
        .petal {
            opacity: 0.8;
        }
    }
</style>
