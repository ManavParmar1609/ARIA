"use client";

import { MoonIcon, SunIcon } from "lucide-react";
import { buttonVariants } from "@/components/ui/button-variants";
import { cx } from "@/lib/cx";
import { useTheme } from "@/lib/theme";

/** One button between the dark and light themes, for pages that carry no menus. */
export function ThemeSwitch({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  // The stored theme is only known in the browser; until hydrated this assumes the default, light.
  const light = resolvedTheme === "light";
  return (
    <button
      type="button"
      className={cx(buttonVariants({ variant: "ghost", size: "icon-sm" }), className)}
      aria-label={light ? "Use the dark theme" : "Use the light theme"}
      onClick={() => setTheme(light ? "dark" : "light")}
    >
      {light ? <MoonIcon aria-hidden /> : <SunIcon aria-hidden />}
    </button>
  );
}
