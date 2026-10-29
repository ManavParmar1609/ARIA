import { cn } from "@/lib/utils";

/** ARIA's mark: a triage tag with its hole punched, beside the name. */
export function Wordmark({
  className,
  withName = true,
}: {
  className?: string;
  withName?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-extrabold tracking-tight", className)}>
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
        <path d="M4 3h11.5L21 8.5V21H4z" className="fill-primary" strokeLinejoin="round" />
        <rect x="4" y="3" width="5" height="18" className="fill-sev2" />
        <circle cx="6.5" cy="7" r="1.4" className="fill-background" />
        <path
          d="M11.5 11h6M11.5 14h6M11.5 17h4"
          className="stroke-primary-foreground"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </svg>
      {withName ? <span className="text-lg leading-none">ARIA</span> : null}
    </span>
  );
}
