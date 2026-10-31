"use client";

import { ChevronDownIcon, LoaderCircleIcon } from "lucide-react";
import { useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { SAMPLE_LOGS, sampleLines, type SampleKind, type SampleLog } from "@/lib/samples";
import { systemName } from "@/lib/systems";
import { cn } from "@/lib/utils";

/** A familiar log, ready for the box: its lines, its format and the title it gives the incident. */
export interface FamiliarLog {
  id: string;
  title: string;
  system: string;
  lines: string[];
}

interface Shown extends SampleLog {
  /** The system that wrote the log, by the name people know it by. */
  name: string;
}

export interface FamiliarGroup {
  name: string;
  /** Shown from the start; the others wait behind "Show all". */
  everyday: boolean;
  logs: Shown[];
}

// The groups the logs are shown in, and each system by the name people know it by. A newcomer
// starts with a handful from the everyday groups, an incident and routine noise among them; the
// rest wait behind "Show all", the most specialised last.
const GROUPS: { name: string; everyday: boolean; systems: Record<string, string> }[] = [
  {
    name: "Security and sign-ins",
    everyday: true,
    systems: { linux: "Linux server", openssh: "SSH server" },
  },
  {
    name: "Phones and computers",
    everyday: true,
    systems: { mac: "Mac", android: "Android phone" },
  },
  {
    name: "Web and cloud",
    everyday: false,
    systems: { apache: "Apache web server", openstack: "OpenStack cloud", proxifier: "Proxifier" },
  },
  {
    name: "Big-data clusters",
    everyday: false,
    systems: { hdfs: "Hadoop storage", hadoop: "Hadoop jobs", zookeeper: "ZooKeeper" },
  },
  {
    name: "Supercomputers",
    everyday: false,
    systems: { bgl: "BlueGene/L", hpc: "Computing cluster" },
  },
];

/** The logs in their groups, in order. A log from a system no group names goes under "Other
 * logs", so a sample added later is never left out. */
export function familiarGroups(logs: readonly SampleLog[] = SAMPLE_LOGS): FamiliarGroup[] {
  const named = new Set(GROUPS.flatMap((group) => Object.keys(group.systems)));
  const groups = GROUPS.map((group) => ({
    name: group.name,
    everyday: group.everyday,
    logs: Object.entries(group.systems).flatMap(([system, name]) =>
      logs.filter((log) => log.system === system).map((log) => ({ ...log, name })),
    ),
  }));
  const other = logs
    .filter((log) => !named.has(log.system))
    .map((log) => ({ ...log, name: systemName(log.system) }));
  return [...groups, { name: "Other logs", everyday: false, logs: other }].filter(
    (group) => group.logs.length > 0,
  );
}

/** The title a familiar log gives the incident, "Linux server: Sign-ins keep failing", or null
 * for a log the picker does not offer. */
export function familiarTitle(id: string): string | null {
  const log = familiarGroups()
    .flatMap((group) => group.logs)
    .find((shown) => shown.id === id);
  return log ? `${log.name}: ${log.label}` : null;
}

const KIND_NAME: Record<SampleKind, string> = { incident: "Incident", routine: "Routine" };

/** What a log whose lines would not load says, on the log itself. */
const UNLOADED = "Couldn’t load it. Choose it to try again.";

/** Incident or routine, as a dot and its name: a filled dot for an incident, an open one for
 * routine noise. While the log's lines load, a spinner takes the dot's place, after a moment, so
 * a quick load never flickers. */
function Kind({ kind, busy }: { kind: SampleKind; busy: boolean }) {
  return (
    <span className="col-start-2 row-start-1 inline-flex items-center gap-1.5 self-start pt-0.5 text-xs font-medium text-muted-foreground">
      <span aria-hidden className="grid size-3.5 place-items-center">
        <span
          className={cn(
            "col-start-1 row-start-1 block size-2 rounded-full",
            kind === "incident" ? "bg-primary" : "border-[1.5px] border-control",
            busy && "animate-out delay-150 fill-mode-forwards fade-out",
          )}
        />
        {busy ? (
          <span className="col-start-1 row-start-1 grid animate-in delay-150 fill-mode-backwards fade-in">
            <LoaderCircleIcon className="size-3.5 animate-spin" strokeWidth={2} />
          </span>
        ) : null}
      </span>
      {KIND_NAME[kind]}
    </span>
  );
}

/** One click puts a familiar log in the box: for someone with no logs of their own at hand. The
 * logs come in groups a newcomer recognises; a log's lines load when it is picked. */
export function FamiliarLogs({
  chosen,
  onPick,
}: {
  /** The log whose lines are in the box, as they were filled in. */
  chosen: string | null;
  /** `keepFocus`: leave focus where it is, because the log was tapped on a touch screen or
   * focus moved on while its lines loaded. */
  onPick: (log: FamiliarLog, keepFocus: boolean) => void;
}) {
  const id = useId();
  const groups = familiarGroups();
  const everyday = groups.filter((group) => group.everyday);
  const first = everyday.length ? everyday : groups;
  const more = everyday.length ? groups.filter((group) => !group.everyday) : [];
  const total = groups.reduce((sum, group) => sum + group.logs.length, 0);
  // A log picked from the longer list stays in view when the page comes back to it.
  const [open, setOpen] = useState(() =>
    more.some((group) => group.logs.some((log) => log.id === chosen)),
  );
  const [pending, setPending] = useState<Shown | null>(null);
  const [failed, setFailed] = useState<Shown | null>(null);
  // What pressed a log last: a finger or a pen, a mouse, or nothing (a key).
  const pointer = useRef("");
  // Only the latest pick fills the box, however the loads finish.
  const latest = useRef(0);

  const pick = async (log: Shown, button: HTMLButtonElement) => {
    const touch = pointer.current === "touch" || pointer.current === "pen";
    pointer.current = "";
    const turn = ++latest.current;
    // Where focus is now: on the button, or (Safari, after a click) on the page.
    const focused = document.activeElement;
    setPending(log);
    setFailed(null);
    try {
      const lines = await sampleLines(log.id);
      if (turn !== latest.current) return;
      onPick(
        { id: log.id, title: familiarTitle(log.id) ?? log.label, system: log.system, lines },
        touch || (document.activeElement !== focused && document.activeElement !== button),
      );
    } catch {
      if (turn === latest.current) setFailed(log);
    } finally {
      if (turn === latest.current) setPending(null);
    }
  };

  const list = (group: FamiliarGroup, index: number) => {
    const heading = `${id}-group-${index}`;
    return (
      <div key={group.name} className="grid gap-2">
        <h3 id={heading} className="text-sm text-muted-foreground">
          {group.name}
        </h3>
        <ul
          aria-labelledby={heading}
          className="grid grid-cols-[minmax(0,1fr)] gap-2 @md:grid-cols-2 @3xl:grid-cols-3"
        >
          {group.logs.map((log) => (
            <li key={log.id} className="grid">
              <button
                type="button"
                aria-pressed={chosen === log.id}
                // What it shows, in reading order, with the pauses a listener needs: from its
                // cells alone a browser would read "Linux server : Sign-ins keep failing".
                aria-label={`${log.name}: ${log.label}, ${KIND_NAME[log.kind].toLowerCase()}${
                  failed?.id === log.id ? `. ${UNLOADED}` : ""
                }`}
                onPointerDown={(event) => {
                  pointer.current = event.pointerType;
                }}
                onKeyDown={() => {
                  pointer.current = "";
                }}
                onClick={(event) => void pick(log, event.currentTarget)}
                className="grid min-h-16 grid-cols-[minmax(0,1fr)_auto] content-start gap-x-3 gap-y-0.5 rounded-md border border-rule bg-background px-4 py-3 text-left transition-[border-color,background-color,scale] duration-(--duration-quick) ease-(--ease-out) hover:border-control active:scale-[0.99] aria-pressed:border-primary aria-pressed:bg-highlight"
              >
                <span className="text-sm leading-5 font-semibold text-heading">{log.name}</span>{" "}
                <span className="col-span-2 row-start-2 text-sm leading-5 text-muted-foreground">
                  {log.label}
                </span>{" "}
                <Kind kind={log.kind} busy={pending?.id === log.id} />{" "}
                {failed?.id === log.id ? (
                  <span className="col-span-2 pt-1 text-xs text-danger">{UNLOADED}</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  };

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="@container grid gap-5 rounded-card border border-rule bg-raised p-5 sm:p-6"
    >
      <div className="grid gap-1">
        <h2 id={`${id}-title`} className="text-lg">
          No logs at hand? Try a familiar one
        </h2>
        <p className="max-w-prose text-sm text-muted-foreground">
          Each fills the box below with real lines from the public Loghub collection. Incidents need
          action; routine logs need none, so they test whether ARIA stays calm.
        </p>
      </div>
      <div className="grid gap-4">
        {first.map(list)}
        {more.length ? (
          <>
            {/* A fold between the everyday logs and the rest. The toggle stays where it was
                pressed, and what it adds follows it, next in the reading and Tab order. */}
            <div className="flex items-center gap-3">
              <Button
                size="sm"
                aria-expanded={open}
                aria-controls={`${id}-more`}
                onClick={() => setOpen(!open)}
              >
                <ChevronDownIcon
                  aria-hidden
                  className={cn(
                    "transition-transform duration-(--duration-quick) ease-(--ease-out)",
                    open && "rotate-180",
                  )}
                />
                {open ? "Show fewer logs" : `Show all ${total} logs`}
              </Button>
              <span aria-hidden className="h-px flex-1 bg-rule" />
            </div>
            <div id={`${id}-more`} hidden={!open} className="grid gap-4">
              {more.map((group, index) => list(group, first.length + index))}
            </div>
          </>
        ) : null}
      </div>
      <p role="status" className="sr-only">
        {pending
          ? `Loading the ${pending.name} log.`
          : failed
            ? `The ${failed.name} log couldn’t load. Choose it to try again.`
            : ""}
      </p>
    </section>
  );
}
