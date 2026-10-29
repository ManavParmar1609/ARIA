import { cn } from "@/lib/utils";

/** ARIA's mark: a small bioluminescent data orb beside the name (DESIGN.md). */
export function Wordmark({
  className,
  withName = true,
}: {
  className?: string;
  withName?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5 font-medium", className)}>
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
        <defs>
          <radialGradient id="aria-orb" cx="38%" cy="34%" r="70%">
            <stop offset="0%" stopColor="#edfffe" />
            <stop offset="45%" stopColor="#cbfffc" />
            <stop offset="80%" stopColor="#00827c" />
            <stop offset="100%" stopColor="#fad1ff" />
          </radialGradient>
        </defs>
        <circle cx="12" cy="12" r="9" fill="url(#aria-orb)" />
        <circle cx="12" cy="12" r="11" fill="none" stroke="#cbfffc" strokeOpacity="0.35" />
      </svg>
      {withName ? <span className="text-base leading-none tracking-[0.12em]">ARIA</span> : null}
    </span>
  );
}
