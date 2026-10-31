"use client";

import { LoaderCircleIcon, MessageSquareTextIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { SeverityBadge } from "@/components/aria/severity";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { useRunState, useScenarios, useStartSample } from "@/lib/api/hooks";
import type { components } from "@/lib/api/schema";
import { isSeverity, type Scenario } from "@/lib/api/types";

// After a sample's triage: run it again at a bigger size, ask about it, or see how it was
// rated. A run started from here carries ?compare= with the run it came from, so its page
// shows the two ratings side by side.

export type SampleRef = components["schemas"]["SampleRef"];

/** The sample a run was built from, read from the run's stored request. */
export function sampleOf(request: Record<string, unknown> | undefined): SampleRef | null {
  const sample = request?.sample;
  if (!sample || typeof sample !== "object") return null;
  const { id, servers, rate } = sample as Record<string, unknown>;
  if (typeof id !== "string" || !id) return null;
  return {
    id,
    servers: typeof servers === "number" ? servers : null,
    rate: typeof rate === "number" ? rate : null,
  };
}

/**
 * A harmless sample says what the right answer was, and whether ARIA got it: a level above SEV4
 * is a false alarm, said plainly rather than left for the reader to spot.
 */
export function HarmlessNote({
  sample,
  severity,
}: {
  sample: SampleRef;
  severity: string | null | undefined;
}) {
  const card = useScenarios().data?.find((s) => s.id === sample.id);
  if (!card?.benign || !isSeverity(severity)) return null;
  if (severity === "SEV4") {
    return (
      <p className="max-w-prose rounded-md bg-ok/10 p-3 text-sm">
        This sample is harmless noise, and ARIA rated it SEV4, as it should.
      </p>
    );
  }
  return (
    <p className="max-w-prose rounded-md bg-sev3/12 p-3 text-sm">
      This sample is harmless noise, so the right level is SEV4. ARIA rated it {severity}: a false
      alarm. The rules that matched are under How serious, in How ARIA decided, and{" "}
      <Link href="/console/evals#q-limits" className="underline underline-offset-4">
        Test results
      </Link>{" "}
      lists where ARIA falls short.
    </p>
  );
}

export interface BiggerRun {
  servers: number | null;
  rate: number | null;
  /** The button's words, for example "Run it on 24 servers". */
  label: string;
}

/** The next size up the sample offers: more servers, or else a faster rate. */
export function biggerRun(card: Scenario | undefined, sample: SampleRef): BiggerRun | null {
  if (card?.servers && sample.servers != null) {
    const next = card.servers.options.find((o) => o.value > (sample.servers ?? 0));
    return next ? { servers: next.value, rate: null, label: `Run it on ${next.label}` } : null;
  }
  if (card?.rate && sample.rate != null) {
    const next = card.rate.options.find((o) => o.value > (sample.rate ?? 0));
    return next
      ? { servers: null, rate: next.value, label: `Run it faster, at ${next.label}` }
      : null;
  }
  return null;
}

/** "on 6 servers" or "at 60 lines a minute": the size a sample ran at, in the card's words. */
export function sizeWords(sample: SampleRef | null): string {
  if (sample?.servers != null)
    return sample.servers === 1 ? "on 1 server" : `on ${sample.servers} servers`;
  if (sample?.rate != null) return `at ${sample.rate} lines a minute`;
  return "";
}

function Compared({
  runId,
  sample,
  severity,
}: {
  runId: string;
  sample: SampleRef;
  severity: string | null | undefined;
}) {
  // Another visitor's run, or one since deleted, is a 404: then there is nothing to compare.
  const other = useRunState(runId);
  const values = other.data?.values;
  const before = values?.severity?.severity;
  if (!values || !before) return null;
  const was = sizeWords(sampleOf(values.request));
  const now = sizeWords(sample);
  return (
    <div className="grid gap-2">
      <p className="text-sm font-medium">The same sample at two sizes</p>
      <ul className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <li>
          <Link
            href={`/console/runs/${encodeURIComponent(runId)}` as never}
            className="flex items-center gap-2 underline-offset-4 hover:underline"
          >
            <SeverityBadge severity={isSeverity(before) ? before : null} size="sm" />
            {was ? `The first run, ${was}` : "The first run"}
          </Link>
        </li>
        <li className="flex items-center gap-2">
          <SeverityBadge severity={isSeverity(severity) ? severity : null} size="sm" />
          {now ? `This run, ${now}` : "This run"}
        </li>
      </ul>
    </div>
  );
}

/** Ways to keep exploring once a sample's triage is done. */
export function SampleNext({
  runId,
  sample,
  severity,
  waiting = false,
}: {
  runId: string;
  sample: SampleRef;
  severity: string | null | undefined;
  /** The incident waits for review: its approval is the page's one main action. */
  waiting?: boolean;
}) {
  const router = useRouter();
  const compare = useSearchParams().get("compare");
  const card = useScenarios().data?.find((s) => s.id === sample.id);
  const bigger = biggerRun(card, sample);
  const start = useStartSample();
  const starting = useRef(false);
  const [started, setStarted] = useState(false);
  const busy = start.isPending || started;

  const runBigger = () => {
    // A double click would start two runs before the first one's state reached the button.
    if (!bigger || starting.current) return;
    starting.current = true;
    start.mutate(
      {
        id: sample.id,
        body: {
          servers: bigger.servers,
          rate: bigger.rate,
          options: { use_llm: true, investigate: true, require_approval: true },
        },
      },
      {
        onSuccess: (accepted) => {
          setStarted(true);
          const to = `/console/runs/${encodeURIComponent(accepted.run_id)}?compare=${encodeURIComponent(runId)}`;
          router.push(to as never);
        },
        onError: (error) => {
          starting.current = false;
          toast.error("The bigger run could not be started", {
            description: error instanceof ApiError ? error.detail : String(error),
          });
        },
      },
    );
  };

  return (
    <section aria-labelledby="next-title" className="grid gap-4 rounded-lg bg-raised p-5">
      <h2 id="next-title" className="text-base font-medium">
        What next?
      </h2>
      {compare && compare !== runId ? (
        <Compared runId={compare} sample={sample} severity={severity} />
      ) : null}
      <ul className="flex flex-wrap gap-2">
        {bigger ? (
          <li>
            <Button
              size="sm"
              variant={waiting ? "secondary" : "primary"}
              onClick={runBigger}
              disabled={busy}
            >
              {busy ? <LoaderCircleIcon aria-hidden className="animate-spin" /> : null}
              {busy ? "Starting" : bigger.label}
            </Button>
          </li>
        ) : null}
        <li>
          <Button asChild size="sm" variant={bigger || waiting ? "secondary" : "primary"}>
            <Link href={`/console/ask?run=${encodeURIComponent(runId)}` as never}>
              <MessageSquareTextIcon aria-hidden />
              Ask about this incident
            </Link>
          </Button>
        </li>
        <li>
          <Button asChild size="sm" variant="ghost">
            <a href="#severity-title">How was this rated?</a>
          </Button>
        </li>
      </ul>
    </section>
  );
}
