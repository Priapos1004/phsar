/**
 * Centralized theme configuration — single source of truth for:
 *   theme → CSS class, character pic, and display label.
 *
 * Pic files live in /static/profile_pics/<color>.png.
 * Every component that needs theme info imports from here.
 */

export const THEMES = {
	default: { label: 'Default', pic: '/profile_pics/rainbow.png', cssClass: null, focal: '55%' },
	red: { label: 'Crimson', pic: '/profile_pics/red.png', cssClass: 'theme-red', focal: '55%' },
	blue: { label: 'Ocean', pic: '/profile_pics/blue.png', cssClass: 'theme-blue', focal: '77.5%' },
	green: { label: 'Forest', pic: '/profile_pics/green.png', cssClass: 'theme-green', focal: '77.5%' },
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
 * Yearly variants of every theme's pic, `/profile_pics/<color>_<suffix>.png`, shown from
 * `from` to `to` inclusive. A suffix needs a file for every theme. A range may cross New
 * Year. Read off the viewer's own clock: it is decoration, so no two viewers need agree.
 *
 * `focal` overrides the theme's own where a variant's subject sits elsewhere in the
 * frame. Tune it at the banner's widest (`cls.container` wide, `sm:h-80` tall), where it crops the most.
 */
const SEASONAL_PICS: readonly {
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

/** A theme's art today, and the vertical point the banner crops it at. */
export function themeArt(key: string, today = new Date()): { pic: string; focal: string } {
	const theme: ThemeKey = isValidTheme(key) ? key : 'default';
	const { pic, focal } = THEMES[theme];
	const season = SEASONAL_PICS.find(({ from, to }) => inYearlyRange(today, from, to));
	if (!season) return { pic, focal };
	return { pic: pic.replace(/\.png$/, `_${season.suffix}.png`), focal: season.focal?.[theme] ?? focal };
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

