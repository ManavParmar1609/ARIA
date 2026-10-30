import { cn } from "@/lib/utils";

/**
 * ARIA's mark: a forest square in which three lines run together into one, the noise of the logs
 * resolving into a single signal (DESIGN.md). Flat fills that follow the theme (forest on cream,
 * keylime after dark), so it needs no ids and copies of it can sit anywhere on a page.
 */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-7", className)} aria-hidden>
      <rect width="32" height="32" rx="8" fill="var(--primary)" />
      <g
        fill="none"
        stroke="var(--primary-foreground)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M6.5 10c6 0 7.5 6 12.5 6M6.5 16H19M6.5 22c6 0 7.5-6 12.5-6M19 16h6.5" />
      </g>
    </svg>
  );
}

export function Wordmark({
  className,
  withName = true,
}: {
  className?: string;
  withName?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <Mark />
      {withName ? (
        <span className="font-display text-[1.75rem] leading-none font-normal tracking-[-0.03em] text-heading">
          aria
        </span>
      ) : null}
    </span>
  );
}
