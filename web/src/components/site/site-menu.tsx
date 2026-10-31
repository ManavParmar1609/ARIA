"use client";

import { ArrowUpRightIcon, EqualIcon, XIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import { ThemeSwitch } from "@/components/theme-switch";
import { buttonVariants } from "@/components/ui/button-variants";
import { cx } from "@/lib/cx";

/**
 * The round menu button and the panel it opens: every section, the source, and the theme.
 * It is the browser's own popover: the button opens it, and a click outside, Escape or a chosen
 * link closes it, handing focus back to the button. While it is open, focus starts on the first
 * link and Tab stays inside it, as in a dialog.
 */
export function SiteMenu({ links }: { links: { href: string; label: string }[] }) {
  const menu = useRef<HTMLElement>(null);
  useEffect(() => {
    const nav = menu.current;
    if (!nav) return;
    const onToggle = (event: Event) => {
      if ((event as ToggleEvent).newState === "open") nav.querySelector<HTMLElement>("a")?.focus();
    };
    const holdTab = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const stops = [...nav.querySelectorAll<HTMLElement>("a, button")];
      if (document.activeElement !== (event.shiftKey ? stops[0] : stops.at(-1))) return;
      event.preventDefault();
      (event.shiftKey ? stops.at(-1) : stops[0])?.focus();
    };
    nav.addEventListener("toggle", onToggle);
    nav.addEventListener("keydown", holdTab);
    return () => {
      nav.removeEventListener("toggle", onToggle);
      nav.removeEventListener("keydown", holdTab);
    };
  }, []);
  return (
    <>
      <button
        type="button"
        popoverTarget="site-menu"
        aria-label="Open the menu"
        className="grid size-10 shrink-0 place-items-center rounded-md bg-foreground/6 text-heading transition-[background-color,scale] duration-(--duration-quick) hover:bg-foreground/10 active:scale-95"
      >
        <EqualIcon aria-hidden className="size-5" strokeWidth={2} />
      </button>
      <nav
        ref={menu}
        id="site-menu"
        popover="auto"
        aria-label="Menu"
        className="inset-x-3 top-3 bottom-auto m-0 h-auto max-h-[calc(100dvh-1.5rem)] w-auto overflow-y-auto rounded-card border border-rule bg-elevated p-4 text-foreground backdrop:bg-black/45 sm:top-24 sm:right-6 sm:left-auto sm:w-80"
      >
        <div className="flex items-center justify-between">
          <span className="pl-3 text-sm font-medium text-muted-foreground">Menu</span>
          <button
            type="button"
            popoverTarget="site-menu"
            popoverTargetAction="hide"
            aria-label="Close the menu"
            className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
          >
            <XIcon aria-hidden />
          </button>
        </div>
        <ul className="mt-2 grid gap-0.5">
          {links.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                onClick={() => menu.current?.hidePopover()}
                className="flex h-12 items-center rounded-sm px-3 text-lg text-heading transition-colors duration-(--duration-quick) hover:bg-foreground/6"
              >
                {link.label}
                {link.href.startsWith("#") ? null : (
                  <ArrowUpRightIcon aria-hidden className="ml-1.5 size-5" />
                )}
              </a>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-rule pt-3 pl-3">
          <span className="text-sm text-muted-foreground">Theme</span>
          <ThemeSwitch className={cx("text-heading")} />
        </div>
      </nav>
    </>
  );
}
