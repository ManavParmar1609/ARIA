"use client";

import { MenuIcon, XIcon } from "lucide-react";
import { useRef } from "react";

import { buttonVariants } from "@/components/ui/button-variants";
import { cx } from "@/lib/cx";

/**
 * The page's sections on small screens, where the header has no room for them. It is the
 * browser's own popover: the button opens it, and a click outside, Escape or a chosen link
 * closes it.
 */
export function SiteMenu({ links }: { links: { href: string; label: string }[] }) {
  const menu = useRef<HTMLElement>(null);
  return (
    <>
      <button
        type="button"
        popoverTarget="site-menu"
        aria-label="Open the menu"
        className={cx(buttonVariants({ variant: "ghost", size: "icon-sm" }), "lg:hidden")}
      >
        <MenuIcon aria-hidden />
      </button>
      <nav
        ref={menu}
        id="site-menu"
        popover="auto"
        aria-label="Menu"
        className="inset-x-3 top-3 bottom-auto m-0 h-auto max-h-[calc(100dvh-1.5rem)] w-auto overflow-y-auto rounded-lg border-0 bg-raised p-5 text-foreground backdrop:bg-sunken/70"
      >
        <div className="flex items-center justify-between">
          <span className="eyebrow pl-3 text-muted-foreground">Menu</span>
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
        <ul className="mt-3 grid gap-1">
          {links.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                onClick={() => menu.current?.hidePopover()}
                className="flex h-12 items-center rounded-md px-3 text-lg text-heading transition-colors duration-(--duration-quick) hover:bg-foreground/8"
              >
                {link.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}
