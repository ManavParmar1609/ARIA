"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

export interface TocItem {
  id: string;
  label: string;
  children?: { id: string; label: string }[];
}

/** Every id the list links to, groups and their entries alike, in page order. */
const allIds = (items: TocItem[]) =>
  items.flatMap((item) => [item.id, ...(item.children ?? []).map((child) => child.id)]);

/** The section being read: the last one whose heading has passed a line near the top. */
function useCurrent(ids: string[]): string | null {
  const [current, setCurrent] = useState<string | null>(null);
  useEffect(() => {
    const seen = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting || entry.boundingClientRect.top < 0) seen.add(entry.target.id);
          else seen.delete(entry.target.id);
        }
        setCurrent(ids.filter((id) => seen.has(id)).at(-1) ?? null);
      },
      // A heading counts once it is above the lower two-thirds of the screen.
      { rootMargin: "0px 0px -66% 0px" },
    );
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [ids]);
  return current;
}

/**
 * A page's sections. As a rail beside the page on a wide screen: each group and the parts under
 * it, with the one being read marked. As chips above the page on a narrower screen: the groups.
 */
export function OnThisPage({
  items,
  variant,
  className,
}: {
  items: TocItem[];
  variant: "rail" | "chips";
  className?: string;
}) {
  const [ids] = useState(() => allIds(items));
  const current = useCurrent(ids);
  const group = items.find(
    (item) => item.id === current || item.children?.some((child) => child.id === current),
  );
  const link = (active: boolean) =>
    cn(
      "block rounded-sm py-1 transition-colors duration-(--duration-quick) hover:text-heading",
      active ? "font-medium text-heading" : "text-muted-foreground",
    );
  if (variant === "chips") {
    return (
      <nav aria-label="Sections" className={cn("xl:hidden", className)}>
        <ul className="flex flex-wrap gap-2">
          {items.map((item) => (
            <li key={item.id}>
              <a
                href={`#${item.id}`}
                className="inline-flex min-h-9 items-center rounded-full border border-rule bg-raised px-4 text-sm font-medium text-heading transition-colors duration-(--duration-quick) hover:border-control"
              >
                {item.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    );
  }
  return (
    <>
      <nav aria-label="On this page" className={cn("hidden xl:block", className)}>
        <div className="sticky top-6 grid max-h-[calc(100dvh-3rem)] gap-3 overflow-y-auto pb-6">
          <p className="text-sm font-semibold text-heading">On this page</p>
          <ol className="grid gap-3 border-l border-rule pl-4 text-sm">
            {items.map((item) => (
              <li key={item.id} className="grid gap-1">
                <a
                  href={`#${item.id}`}
                  aria-current={item.id === group?.id ? "true" : undefined}
                  className={link(item.id === group?.id)}
                >
                  {item.label}
                </a>
                {item.children?.length ? (
                  <ol className="grid gap-0.5 pl-3">
                    {item.children.map((child) => (
                      <li key={child.id}>
                        <a
                          href={`#${child.id}`}
                          aria-current={child.id === current ? "true" : undefined}
                          className={cn(link(child.id === current), "text-[0.8125rem]")}
                        >
                          {child.label}
                        </a>
                      </li>
                    ))}
                  </ol>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      </nav>
    </>
  );
}
