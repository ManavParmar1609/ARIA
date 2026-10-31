import {
  FileCheck2Icon,
  GaugeIcon,
  HistoryIcon,
  ShieldCheckIcon,
  type LucideIcon,
} from "lucide-react";

/** What ARIA does for the person on call, as four plain cards with forest line icons. */
const POINTS: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: GaugeIcon,
    title: "Severity you can check",
    body: "Rules and a calibrated model agree on a short list of likely levels, and say when they aren't sure. Safety floors stop a dangerous pattern from being rated too low.",
  },
  {
    icon: FileCheck2Icon,
    title: "Every claim cites its evidence",
    body: "A check rejects any sentence whose source is missing or whose numbers disagree with the logs.",
  },
  {
    icon: HistoryIcon,
    title: "Remembers last time",
    body: "Search finds similar past incidents and the runbooks that resolved them.",
  },
  {
    icon: ShieldCheckIcon,
    title: "Keeps bad input out",
    body: "Secrets and personal details are masked, and a line that reads like an instruction is set aside before any model sees the logs.",
  },
];

export function Why() {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {POINTS.map(({ icon: Icon, title, body }) => (
        <li
          key={title}
          // Each card spans three rows of the list, so titles and bodies line up across a row.
          className="row-span-3 grid grid-rows-subgrid gap-4 rounded-card border border-rule bg-raised p-7"
        >
          <span className="grid size-11 place-items-center rounded-[10px] bg-panel-keylime text-heading">
            <Icon aria-hidden className="size-5" strokeWidth={1.5} />
          </span>
          <h3 className="text-[1.4375rem] leading-snug">{title}</h3>
          <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
        </li>
      ))}
    </ul>
  );
}
