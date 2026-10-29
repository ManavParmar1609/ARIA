// Shared by the root layout (a server component) and the theme store in ./theme.

/** Where the theme choice is stored, and the media query behind "match my system". */
export const THEME_KEY = "theme";
export const PREFERS_LIGHT = "(prefers-color-scheme: light)";

/** Runs in <head> before first paint, so a stored light theme never flashes dark. */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");document.documentElement.classList.toggle("dark",!(t==="light"||(t==="system"&&matchMedia("${PREFERS_LIGHT}").matches)))}catch(e){}`;
