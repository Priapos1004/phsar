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

export function getThemePic(key: string): string {
	if (isValidTheme(key)) return THEMES[key].pic;
	return THEMES.default.pic;
}

export function getThemeFocal(key: string): string {
	if (isValidTheme(key)) return THEMES[key].focal;
	return THEMES.default.focal;
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

