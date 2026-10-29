import { cn } from "@/lib/utils";

/**
 * ARIA's mark: a grass-green disc holding a single-storey "a" drawn as a lens and its handle, the
 * look-closer step of triage (DESIGN.md). Flat fills only, so it needs no ids and copies of it can
 * sit anywhere on a page.
 */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-7", className)} aria-hidden>
      <circle cx="12" cy="12" r="12" fill="#8ed462" />
      <circle cx="10.4" cy="12.6" r="4.3" fill="none" stroke="#2c2e2a" strokeWidth="2.6" />
      <path d="M15.2 8.2v9" stroke="#2c2e2a" strokeWidth="2.6" strokeLinecap="round" />
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
    <span className={cn("inline-flex items-center gap-2.5 font-medium", className)}>
      <Mark />
      {withName ? (
        <span className="text-xl leading-none tracking-[-0.01em] text-heading">ARIA</span>
      ) : null}
    </span>
  );
}
