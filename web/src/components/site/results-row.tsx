import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";

import type { Evaluation, RealLogs } from "@/lib/site-data";

// The home page's results (item 28): one row of findings, each computed from the published
// results and linked to its test on Test results. Test results answers the same questions in
// full, including where ARIA falls short.

const per100 = (x: number) => Math.round(x * 100);
const count = (x: number) => x.toLocaleString("en");

export interface ResultTile {
  figure: string;
  label: string;
  href: string;
  link: string;
}

export function resultTiles(data: Evaluation, real: RealLogs): ResultTile[] {
  const life = real.lifecycle;
  const caught = life.flagged - life.falseAlarms;
  const best = [...real.detectors].sort(
    (a, b) => b.recall - a.recall || a.falseAlarms - b.falseAlarms,
  )[0];
  const rival = !best
    ? ""
    : best.flagged - best.falseAlarms === caught && best.falseAlarms === life.falseAlarms
      ? " The best standard detector did the same."
      : ` The best standard detector caught ${count(best.flagged - best.falseAlarms)}, with ${count(best.falseAlarms)} false alarms.`;
  const s = data.severity;
  const p = data.pipeline;
  return [
    {
      figure: `${count(caught)} of ${count(real.judgedFailed)}`,
      label: `failed storage blocks caught on a real Hadoop cluster, as its experts judged them, with ${count(life.falseAlarms)} false alarms among ${count(life.healthy)} healthy ones.${rival}`,
      href: "/console/evals#ev-real",
      link: "The real cluster test",
    },
    {
      figure: `${per100(s.autoDecided)} in 100`,
      label: `test incidents, built from real log lines, were rated without asking a person. Of those, ${per100(s.accuracyWhenAuto)} in 100 were right. ARIA asked a person about the rest, the harder ones.`,
      href: "/console/evals#ev-calibration",
      link: "When it asks a person",
    },
    {
      figure: p.valid === 1 ? "Every report" : `${per100(p.valid)} in 100 reports`,
      label: "passed the check that each claim cites its evidence and agrees with it.",
      href: "/console/evals#ev-pipeline",
      link: "The end-to-end test",
    },
  ];
}

export function ResultsRow({ data, real }: { data: Evaluation; real: RealLogs }) {
  return (
    <ul className="grid gap-3 md:grid-cols-3">
      {resultTiles(data, real).map((tile) => (
        <li key={tile.href} className="flex flex-col gap-3 rounded-card bg-raised p-6">
          <p className="stat text-[2rem] leading-none whitespace-nowrap">{tile.figure}</p>
          <p className="text-sm leading-relaxed text-foreground">{tile.label}</p>
          <Link
            href={tile.href as never}
            prefetch={false}
            className="mt-auto inline-flex w-fit items-center gap-1.5 pt-1 text-sm font-medium text-heading underline decoration-control underline-offset-4 hover:decoration-heading"
          >
            {tile.link}
            <ArrowRightIcon aria-hidden className="size-4" />
          </Link>
        </li>
      ))}
    </ul>
  );
}
