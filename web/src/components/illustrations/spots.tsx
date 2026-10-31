/*
 * Small line drawings for the console's quiet moments: a first visit, an empty queue, a search
 * with no match, a page that does not exist. Forest ink on soft panel shapes, in the same hand as
 * the landing page's line art (DESIGN.md). Decorative only, so each is aria-hidden. Colours come
 * from the theme, so they follow it after dark.
 */

const INK = "var(--heading)";
const PANEL = "var(--panel-keylime)";
const PANEL2 = "var(--panel-sage)";

function Frame({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <svg viewBox="0 0 260 200" className={className} aria-hidden focusable="false">
      <g fill="none" stroke={INK} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        {children}
      </g>
    </svg>
  );
}

/** All clear: rings settling outward from a quiet point. */
export function AllClearSpot({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <circle cx="130" cy="100" r="72" fill={PANEL} stroke="none" />
      {[18, 34, 50, 66].map((r) => (
        <circle key={r} cx="130" cy="100" r={r} opacity={1 - r / 110} />
      ))}
      <path d="M117 100l9 9 17-19" strokeWidth="2.25" />
    </Frame>
  );
}

/** No match: a lens over lines that hold nothing like the search. */
export function SearchSpot({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <rect x="30" y="34" width="150" height="132" rx="14" fill={PANEL} stroke="none" />
      {[62, 82, 102, 122, 142].map((y, i) => (
        <path key={y} d={`M52 ${y}H${148 - ((i * 19) % 46)}`} opacity="0.55" />
      ))}
      <circle cx="170" cy="104" r="34" fill={PANEL2} />
      <path d="M195 129l26 26" strokeWidth="2.25" />
    </Frame>
  );
}

/** Not found: a line that runs on and breaks off. */
export function LostSpot({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <rect x="24" y="40" width="212" height="120" rx="14" fill={PANEL} stroke="none" />
      <path d="M44 120C80 120 90 80 126 80" />
      <path d="M146 80C170 80 176 104 196 104" strokeDasharray="2 7" />
      <circle cx="126" cy="80" r="4" fill={INK} />
      <path d="M206 62c0-8 5-12 11-12s11 4 11 10c0 7-9 8-9 14" strokeWidth="2" />
      <circle cx="219" cy="86" r="1.6" fill={INK} />
    </Frame>
  );
}
