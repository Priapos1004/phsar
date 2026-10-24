/**
 * Centralized theme configuration — single source of truth for:
 *   theme → CSS class, character pic, and display label.
 *
 * Pics are served as WebP: `static/profile_pics/<art>.webp` for the banner and
 * `static/profile_pics/thumbs/<art>.webp` for the settings tiles (`themeArt` builds both). The 1536×1024 PNG
 * originals stay in `art/profile_pics/` (not served — a hero PNG is 2–3 MB); a new or
 * edited pic is converted from there:
 *   cwebp -q 85 art/profile_pics/<name>.png -o static/profile_pics/<name>.webp
 *   cwebp -q 85 -resize 448 0 art/profile_pics/<name>.png -o static/profile_pics/thumbs/<name>.webp
 * (448: twice the settings tile's widest, `sm:w-56`, for a sharp tile on a retina screen)
 * Every component that needs theme info imports from here.
 */

export const THEMES = {
	default: { label: 'Default', art: 'rainbow', cssClass: null, focal: '55%' },
	red: { label: 'Crimson', art: 'red', cssClass: 'theme-red', focal: '55%' },
	blue: { label: 'Ocean', art: 'blue', cssClass: 'theme-blue', focal: '77.5%' },
	green: { label: 'Forest', art: 'green', cssClass: 'theme-green', focal: '77.5%' },
} as const;

export type ThemeKey = keyof typeof THEMES;

const THEME_KEYS = Object.keys(THEMES) as ThemeKey[];

export function isValidTheme(key: string): key is ThemeKey {
	return THEME_KEYS.includes(key as ThemeKey);
}

export function getThemeCssClass(key: string): string | null {
	if (isValidTheme(key)) return THEMES[key].cssClass;
	return null;
}

type MonthDay = readonly [month: number, day: number];

/**
 * Yearly variants of every theme's pic, `<art>_<suffix>` (both files), shown from
 * `from` to `to` inclusive. A suffix needs a file for every theme. A range may cross New
 * Year. Read off the viewer's own clock: it is decoration, so no two viewers need agree.
 *
 * `focal` overrides the theme's own where a variant's subject sits elsewhere in the
 * frame. Tune it at the banner's widest below `2xl` (`cls.container` wide, `sm:h-80` tall),
 * where it crops the most; `InfoDiashow` keeps that framing above it.
 */
export const SEASONAL_PICS: readonly {
	suffix: string; from: MonthDay; to: MonthDay; focal?: Partial<Record<ThemeKey, string>>;
}[] = [
	{ suffix: 'halloween', from: [10, 1], to: [10, 31], focal: { red: '70%', green: '55%' } },
];

/** Whether `today` falls in the yearly range — one whose start comes after its end wraps over New Year. */
export function inYearlyRange(today: Date, from: MonthDay, to: MonthDay): boolean {
	const day = (today.getMonth() + 1) * 100 + today.getDate();
	const [start, end] = [from[0] * 100 + from[1], to[0] * 100 + to[1]];
	return start <= end ? start <= day && day <= end : day >= start || day <= end;
}

/** A theme's art today — the banner pic, its settings-tile thumbnail — and the vertical
 * point the banner crops it at. */
export function themeArt(key: string, today = new Date()): { pic: string; thumb: string; focal: string } {
	const theme: ThemeKey = isValidTheme(key) ? key : 'default';
	const season = SEASONAL_PICS.find(({ from, to }) => inYearlyRange(today, from, to));
	const name = season ? `${THEMES[theme].art}_${season.suffix}` : THEMES[theme].art;
	const focal = season?.focal?.[theme] ?? THEMES[theme].focal;
	return { pic: `/profile_pics/${name}.webp`, thumb: `/profile_pics/thumbs/${name}.webp`, focal };
}

/** Detects the active theme from the CSS class on <html>. */
export function getActiveTheme(): ThemeKey {
	if (typeof document === 'undefined') return 'default';
	const el = document.documentElement;
	for (const [key, cfg] of Object.entries(THEMES)) {
		if (cfg.cssClass && el.classList.contains(cfg.cssClass)) return key as ThemeKey;
	}
	return 'default';
}

