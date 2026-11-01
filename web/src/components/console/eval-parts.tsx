import { ArrowUpRightIcon, ChevronRightIcon } from "lucide-react";
import { type ReactNode } from "react";

import { RollingNumber } from "@/components/aria/rolling-number";
import { TuningBadge } from "@/components/console/tuning-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Tuning } from "@/lib/tuning";
import { cn } from "@/lib/utils";

// The parts Test results builds each test's card from (evals.tsx, eval-domains.tsx).

export const pct = (x: number | undefined, digits = 1) =>
  x == null ? "" : `${(x * 100).toFixed(digits)}%`;

/**
 * One test: what it asks, the result in a plain sentence, and how it was measured, folded away
 * until asked for. The tuning record's badge for the test sits beside its title.
 */
export function Section({
  id,
  title,
  what,
  verdict,
  headline,
  shortfall,
  intro,
  source,
  link,
  tuning,
  level = 3,
  children,
}: {
  id: string;
  title: string;
  /** One sentence on what was tested. */
  what: ReactNode;
  /** What the result means for the person on call, in one plain sentence: it opens the result. */
  verdict?: string;
  /** The result, beside the strongest simple method. */
  headline?: ReactNode;
  /** Where ARIA falls short on this test, in a line under the result. */
  shortfall?: ReactNode;
  /** How it was tested, in full: shown with the details. */
  intro?: ReactNode;
  /** Where the data and its labels come from. */
  source?: string;
  /** This test's section of the full write-up. */
  link?: string;
  /** What the test's results were used for, from the tuning record. */
  tuning?: Tuning | null;
  /** 4 for a card in a group that has its own heading. */
  level?: 3 | 4;
  children: ReactNode;
}) {
  const Heading = level === 4 ? "h4" : "h3";
  return (
    <section
      aria-labelledby={id}
      className="grid gap-4 rounded-card border border-rule bg-raised p-5 sm:p-6"
    >
      <div className="grid max-w-3xl gap-1.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {/* Clear of the sticky phone header when a link jumps here. */}
          <Heading id={id} className="scroll-mt-24 text-xl leading-snug lg:scroll-mt-8">
            {title}
          </Heading>
          {tuning ? <TuningBadge id={id} tuning={tuning} context={title} /> : null}
        </div>
        <p className="text-base text-muted-foreground">{what}</p>
      </div>
      {verdict || headline ? (
        <div className="grid max-w-3xl gap-1 rounded-md bg-panel-keylime px-4 py-3">
          <p className="text-sm font-semibold text-heading">Result</p>
          {verdict ? (
            <p className="text-lg leading-relaxed font-medium text-foreground">{verdict}</p>
          ) : null}
          {headline ? (
            <p className="text-base leading-relaxed text-foreground">{headline}</p>
          ) : null}
        </div>
      ) : null}
      {shortfall ? (
        <p className="max-w-3xl text-base leading-relaxed text-foreground">
          <span className="font-semibold text-heading">Where it falls short: </span>
          {shortfall}
        </p>
      ) : null}
      <details className="group">
        <summary className="inline-flex min-h-9 w-fit cursor-pointer items-center gap-1.5 rounded-sm text-sm font-medium text-heading underline decoration-control underline-offset-4 hover:decoration-heading [&::-webkit-details-marker]:hidden">
          <ChevronRightIcon
            aria-hidden
            className="size-4 transition-transform duration-(--duration-quick) group-open:rotate-90 motion-reduce:transition-none"
          />
          {/* Named for its test, so a list of the page's controls tells them apart (RQ-p2). */}
          <span className="group-open:hidden">
            Show how it was measured<span className="sr-only">: {title}</span>
          </span>
          <span className="hidden group-open:inline">
            Hide how it was measured<span className="sr-only">: {title}</span>
          </span>
        </summary>
        <div className="grid gap-5 pt-5">
          {intro ? <p className="max-w-prose text-sm text-muted-foreground">{intro}</p> : null}
          {children}
          {source ? (
            <p className="max-w-prose text-xs leading-5 text-faint">Source: {source}</p>
          ) : null}
        </div>
      </details>
      {link ? (
        <a
          href={link}
          className="-mt-2 inline-flex min-h-9 w-fit items-center gap-1.5 text-sm font-medium text-heading underline decoration-control underline-offset-4 hover:decoration-heading"
        >
          Read this test in the full write-up<span className="sr-only">: {title}</span>
          <ArrowUpRightIcon aria-hidden className="size-4" />
        </a>
      ) : null}
    </section>
  );
}

/**
 * A row of figures, each over its label, and under it a note where it has one, such as its 95%
 * interval. A figure never wraps ("3 of 5,186" stays on one line), so the row wraps instead: two
 * to a line on a phone, three on wider screens, and a long figure takes the width it needs, alone
 * on its line if it must. Capped at three across, so labels stay short.
 */
export function Facts({ items }: { items: [label: string, value: string, note?: string][] }) {
  return (
    <dl className="flex max-w-3xl flex-wrap gap-6">
      {items.map(([label, value, note]) => (
        <div
          key={label}
          className="grid flex-[1_1_6.5rem] content-start gap-2 border-t border-rule pt-3 sm:basis-[11.5rem]"
        >
          <dt className="order-2 text-sm text-muted-foreground">{label}</dt>
          <dd className="stat order-1 text-[1.75rem] whitespace-nowrap">
            <RollingNumber value={value} />
          </dd>
          {note ? <dd className="tabular order-3 text-xs text-muted-foreground">{note}</dd> : null}
        </div>
      ))}
    </dl>
  );
}

/** Horizontal bars with the value written at the end; real text, no script. */
export function Bars({
  rows,
  max = 1,
  format = (v: number) => pct(v),
  label,
}: {
  rows: [string, number][];
  max?: number;
  format?: (v: number) => string;
  label: string;
}) {
  return (
    <ul aria-label={label} className="grid gap-1.5">
      {rows.map(([name, value]) => (
        <li
          key={name}
          className="grid grid-cols-[minmax(0,7rem)_1fr_3.5rem] items-center gap-3 text-sm sm:grid-cols-[minmax(7rem,11rem)_1fr_4rem]"
        >
          {/* Labels wrap rather than cut: "First assignment group" must stay readable. */}
          <span className="text-pretty text-muted-foreground">{name}</span>
          <span className="h-2.5 rounded-xs bg-sunken" aria-hidden>
            <span
              className="block h-2.5 rounded-xs bg-primary/80"
              style={{ width: `${Math.min(100, (value / max) * 100)}%` }}
            />
          </span>
          <span className="tabular text-right">{format(value)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Methods down the side, measures across; ARIA's own row (`strong`) is highlighted. */
export function MethodTable({
  label,
  head,
  rows,
}: {
  label: string;
  head: string[];
  rows: { name: string; cells: string[]; strong?: boolean }[];
}) {
  return (
    <Table aria-label={label}>
      <TableHeader>
        <TableRow>
          {head.map((h, i) => (
            <TableHead key={h} className={i > 0 ? "text-right" : undefined}>
              {h}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.name} className={cn(row.strong && "bg-highlight/40")}>
            <TableHead scope="row" className={cn(row.strong && "text-foreground")}>
              {row.name}
            </TableHead>
            {row.cells.map((cell, i) => (
              <TableCell key={i} className="tabular text-right">
                {cell}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
