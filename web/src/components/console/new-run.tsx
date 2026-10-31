"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";

import { SampleGallery } from "@/components/console/sample-gallery";
import { PageHeader } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api/client";
import { useCreateRun, useModelKey, useSettingsView } from "@/lib/api/hooks";
import { modelKeyLabel } from "@/lib/api/model-key";
import { MAX_BODY_BYTES } from "@/lib/limits";
import samples from "@/data/samples.json";
import { SYSTEM_NAMES } from "@/lib/systems";
import {
  accessSentence,
  modelAccess,
  type ModelAccess,
  type SharedModel,
} from "@/lib/model-access";

const MAX_LINES = 20_000;

/** A size in megabytes, to one decimal place: "3.7 MB". A paste's size rounds up, so one just
 * over a limit never reads as the limit itself. */
export function megabytes(bytes: number, round: (x: number) => number = Math.round): string {
  return `${round((bytes / 1024 / 1024) * 10) / 10} MB`;
}

function Toggle({
  id,
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-t border-rule py-3">
      <div className="grid gap-0.5">
        <Label htmlFor={id}>{label}</Label>
        <p id={`${id}-hint`} className="text-sm text-muted-foreground">
          {hint}
        </p>
      </div>
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        aria-describedby={`${id}-hint`}
      />
    </div>
  );
}

/** The hint under the log box: what is wrong with the lines, else what happens to them, including
 * which model they go to with the model switch on. A key of the visitor's own is mentioned only
 * where this server accepts one. */
export function logsHint(
  problem: string | null,
  publicDemo: boolean,
  keys = false,
  answers: ModelAccess["kind"] | "off" = "offline",
): string {
  if (problem) return problem;
  const model =
    answers === "own"
      ? " They are also sent to your own key's model."
      : answers === "shared"
        ? ` They are also sent to the site's model${keys ? ", or to your own key's once you add one" : ""}.`
        : answers === "offline" && keys
          ? " If you add a model key, they are sent to that model too."
          : "";
  return publicDemo
    ? `One event per line. Your logs stay with your incident, and only you see it, but this public demo runs on a shared server: paste only logs you could share.${model}`
    : `One event per line. Your logs stay with your incident until you delete it, with IP and e-mail addresses pseudonymised and secrets redacted.${model}`;
}

/** What the model switch does here, as it is set: whose model answers while it is on, and what
 * writes the triage while it is off. */
export function modelHint(
  kinds: string[],
  savedProvider: string | null,
  shared?: SharedModel | null,
  on = true,
): string {
  if (!on) {
    return "Off: rules, the calibrated model and the grounded template write this triage. Faster, and nothing leaves the server.";
  }
  const access = modelAccess(savedProvider, kinds, shared);
  if (access.kind === "own") {
    return `On: your own ${modelKeyLabel(savedProvider ?? "")} key answers first.`;
  }
  if (access.kind === "shared") {
    return access.left == null
      ? "On: the site's key answers."
      : `On: the site's key answers (shared, limited: ${access.left} left today).`;
  }
  if (access.usedUp) return accessSentence(access, kinds.length > 0);
  if (kinds.length > 0) {
    return "No model answers here yet, so this triage runs offline. To use a model, add your own key in Settings.";
  }
  return "No model is set up on this server, so this triage runs offline. Faster, and nothing leaves the server.";
}

/** New triage: pick a sample, or paste your own logs. The open tab stays in the address. */
export function NewRun({ publicDemo = false }: { publicDemo?: boolean }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = params.get("tab") === "own" ? "own" : "samples";
  const setTab = (value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value === "own") next.set("tab", "own");
    else next.delete("tab");
    const qs = next.toString();
    // Like a source filter, a tab is a step Back can undo.
    router.push((qs ? `${pathname}?${qs}` : pathname) as never, { scroll: false });
  };
  return (
    <div className="grid gap-8">
      <PageHeader
        title="New triage"
        description="Choose where the logs come from and an issue to triage, or paste your own logs. ARIA reads them, rates how serious the incident is and drafts a report with its sources. Nothing is sent until you approve it."
      >
        <p className="flex flex-wrap items-center gap-x-1 text-sm text-muted-foreground">
          New here?
          <Link
            href="/console/guide"
            className="inline-flex min-h-6 items-center underline underline-offset-4 hover:text-heading"
          >
            Start with the guide
          </Link>
        </p>
      </PageHeader>
      <Tabs value={tab} onValueChange={setTab} className="grid gap-8">
        <TabsList aria-label="What to triage">
          <TabsTrigger value="samples">Samples</TabsTrigger>
          <TabsTrigger value="own">Your own logs</TabsTrigger>
        </TabsList>
        {/* Each panel starts with controls of its own, so the panel itself is no extra Tab stop. */}
        <TabsContent value="samples" tabIndex={-1}>
          <SampleGallery />
        </TabsContent>
        <TabsContent value="own" tabIndex={-1}>
          <OwnLogs publicDemo={publicDemo} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// What a visitor pasted outlives a look at the Samples tab, Back, a trip to another page and a
// reload (FL-03): kept for this browser tab only, and cleared once the triage starts.
const DRAFT_KEY = "aria:own-logs";

interface Draft {
  title: string;
  system: string;
  text: string;
  useLlm: boolean;
  investigate: boolean;
  approval: boolean;
}

const BLANK: Draft = {
  title: "",
  system: "generic",
  text: "",
  useLlm: true,
  investigate: true,
  approval: true,
};

export function loadDraft(storage: Pick<Storage, "getItem"> | undefined): Draft {
  try {
    const raw: unknown = JSON.parse(storage?.getItem(DRAFT_KEY) ?? "null");
    if (!raw || typeof raw !== "object") return BLANK;
    const d = raw as Partial<Record<keyof Draft, unknown>>;
    return {
      title: typeof d.title === "string" ? d.title : "",
      system: typeof d.system === "string" ? d.system : "generic",
      text: typeof d.text === "string" ? d.text : "",
      useLlm: d.useLlm !== false,
      investigate: d.investigate !== false,
      approval: d.approval !== false,
    };
  } catch {
    return BLANK;
  }
}

function saveDraft(draft: Draft) {
  try {
    const blank = (Object.keys(BLANK) as (keyof Draft)[]).every((k) => draft[k] === BLANK[k]);
    if (blank) window.sessionStorage.removeItem(DRAFT_KEY);
    else window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  } catch {
    // Too big for storage, or storage is blocked: the form still works, it is just not kept.
  }
}

// Logs most people recognise, from the real-line samples the console ships
// (scripts/export_web_samples.py): one click fills the box, ready to read, edit or run.
const FAMILIAR: { id: string; name: string; what: string }[] = [
  { id: "linux.auth_failures", name: "Linux server", what: "sign-ins keep failing" },
  { id: "apache.mod_jk_worker_error", name: "Apache web server", what: "it loses its backends" },
  { id: "openssh.bruteforce", name: "SSH server", what: "someone guesses passwords" },
  { id: "mac.cocoa_scripting_noise", name: "Mac", what: "harmless app errors" },
  { id: "android.permission_noise", name: "Android phone", what: "harmless permission warnings" },
  {
    id: "openstack.image_cache_missing",
    name: "OpenStack cloud",
    what: "servers miss their disk images",
  },
  { id: "hdfs.block_serve_exceptions", name: "Hadoop storage", what: "servers stop sending data" },
  { id: "zookeeper.quorum_connection_loss", name: "ZooKeeper", what: "servers lose touch" },
];

type FamiliarLog = { title: string; system: string; lines: string[] };

/** One click puts a familiar log in the box: for someone with no logs of their own at hand. */
function FamiliarLogs({
  chosen,
  onPick,
}: {
  chosen: string;
  /** `touch`: picked on a touch screen, so focus should stay where it is. */
  onPick: (log: FamiliarLog, touch: boolean) => void;
}) {
  const id = useId();
  // What pressed a log last: a finger or a pen, a mouse, or nothing (a key).
  const pointer = useRef("");
  const byId = new Map(samples.map((sample) => [sample.id, sample]));
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="grid gap-3 rounded-card border border-rule bg-raised p-5 sm:p-6"
    >
      <div className="grid gap-1">
        <h2 id={`${id}-title`} className="text-lg">
          No logs at hand? Try a familiar one
        </h2>
        <p className="max-w-prose text-sm text-muted-foreground">
          Each fills the box below with real lines from that kind of log, from the public Loghub
          collection. Read or edit them, then start the triage.
        </p>
      </div>
      <ul className="flex flex-wrap gap-2">
        {FAMILIAR.map((log) => {
          const sample = byId.get(log.id);
          if (!sample) return null;
          const text = sample.lines.join("\n");
          return (
            <li key={log.id}>
              <button
                type="button"
                aria-pressed={chosen === text}
                onPointerDown={(event) => {
                  pointer.current = event.pointerType;
                }}
                onKeyDown={() => {
                  pointer.current = "";
                }}
                onClick={() => {
                  const touch = pointer.current === "touch" || pointer.current === "pen";
                  pointer.current = "";
                  onPick(
                    {
                      title: `${log.name}: ${log.what}`,
                      system: sample.system,
                      lines: sample.lines,
                    },
                    touch,
                  );
                }}
                className="inline-flex min-h-10 items-center gap-2 rounded-full border border-rule bg-background px-4 py-1.5 text-left text-sm transition-colors duration-(--duration-quick) hover:border-control aria-pressed:border-primary aria-pressed:bg-highlight"
              >
                <span className="font-semibold text-heading">{log.name}</span>
                <span className="text-muted-foreground">{log.what}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function OwnLogs({ publicDemo }: { publicDemo: boolean }) {
  const id = useId();
  const router = useRouter();
  const create = useCreateRun();
  // This page renders in the browser only (it reads the address), so storage is there to read.
  const [draft] = useState(() =>
    loadDraft(typeof window === "undefined" ? undefined : window.sessionStorage),
  );
  const [title, setTitle] = useState(draft.title);
  const [system, setSystem] = useState(draft.system);
  const [text, setText] = useState(draft.text);
  const [useLlm, setUseLlm] = useState(draft.useLlm);
  const [investigate, setInvestigate] = useState(draft.investigate);
  const [approval, setApproval] = useState(draft.approval);
  const [touched, setTouched] = useState(false);
  // Once the triage has started, the draft is spent: nothing saves it again on the way out.
  const sent = useRef(false);
  useEffect(() => {
    const later = window.setTimeout(() => {
      if (!sent.current) saveDraft({ title, system, text, useLlm, investigate, approval });
    }, 300);
    return () => window.clearTimeout(later);
  }, [title, system, text, useLlm, investigate, approval]);
  // Leaving the tab or the page within that delay keeps the draft too (SL-p3).
  const latest = useRef(draft);
  useEffect(() => {
    latest.current = { title, system, text, useLlm, investigate, approval };
  });
  useEffect(() => {
    const keep = () => {
      if (!sent.current) saveDraft(latest.current);
    };
    window.addEventListener("pagehide", keep);
    return () => {
      window.removeEventListener("pagehide", keep);
      keep();
    };
  }, []);
  // The server's rule wins: where it requires approval, every run waits for a person.
  const settings = useSettingsView().data;
  const approvalRequired = settings?.require_approval ?? true;
  const savedKey = useModelKey().data;
  const answers = modelAccess(
    savedKey?.provider ?? null,
    settings?.visitor_keys ?? [],
    settings?.shared_model,
  ).kind;
  const llmHint = modelHint(
    settings?.visitor_keys ?? [],
    savedKey?.provider ?? null,
    settings?.shared_model,
    useLlm,
  );

  const lines = useMemo(() => text.split(/\r?\n/).filter((l) => l.trim()), [text]);
  // The lines' size as sent (UTF-8 JSON, with room for the other fields), so a paste the
  // console would refuse is caught before it is sent.
  const bytes = useMemo(
    () => new TextEncoder().encode(JSON.stringify(lines)).length + 2048,
    [lines],
  );
  // The smaller of the console's own limit and the server's, so a paste is refused once,
  // here, rather than by the server after it was sent.
  const most = Math.min(MAX_BODY_BYTES, settings?.max_body_bytes ?? MAX_BODY_BYTES);
  const problem =
    lines.length === 0
      ? "Paste at least one log line, or try a familiar log above."
      : lines.length > MAX_LINES
        ? `ARIA reads at most ${MAX_LINES.toLocaleString("en")} lines in one triage; this has ${lines.length.toLocaleString("en")}.`
        : bytes > most
          ? // Just over reads as such: rounded up, it would claim "1.1 MB, more than the 1 MB".
            `These lines come to ${bytes < most * 1.1 ? "just over" : `${megabytes(bytes, Math.ceil)}, more than`} the ${megabytes(most)} this server takes in one triage. Send fewer lines, or split them over several triages.`
          : null;
  const apiError = create.error instanceof ApiError ? create.error.detail : create.error?.message;

  const logsBox = useRef<HTMLTextAreaElement>(null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (problem) {
      // To the box, whose hint now says what is wrong: a screen reader reads it with the box.
      logsBox.current?.focus();
      return;
    }
    create.mutate(
      {
        title: title.trim() || undefined,
        system,
        logs: lines,
        options: { use_llm: useLlm, investigate, require_approval: approvalRequired || approval },
      },
      {
        onSuccess: (accepted) => {
          sent.current = true;
          saveDraft(BLANK);
          // The incident page shows the run starting; no toast needs to say so (item 34).
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
      },
    );
  };

  const pick = (log: FamiliarLog, touch: boolean) => {
    setText(log.lines.join("\n"));
    setSystem(log.system in SYSTEM_NAMES ? log.system : "generic");
    setTitle(log.title);
    setTouched(false);
    const box = logsBox.current;
    // The lines come into view either way, and the count beside them says how many arrived.
    // With a keyboard or a mouse, focus goes to them, so the reader sees what was filled in and
    // the button to start sits below. On a touch screen it stays on the button: focusing the box
    // would raise the on-screen keyboard over "Start a triage".
    if (!touch && !window.matchMedia("(hover: none)").matches) box?.focus({ preventScroll: true });
    box?.scrollIntoView({ block: "nearest" });
  };

  return (
    <div className="grid max-w-4xl gap-10">
      <FamiliarLogs chosen={text} onPick={pick} />
      <form
        onSubmit={submit}
        className="grid gap-6"
        noValidate
        aria-describedby={apiError ? `${id}-api-error` : undefined}
      >
        <div className="grid gap-2">
          <div className="flex items-baseline justify-between gap-4">
            <Label htmlFor={`${id}-logs`}>Log lines</Label>
            <span className="tabular text-xs text-muted-foreground" aria-live="polite">
              {lines.length.toLocaleString("en")} {lines.length === 1 ? "line" : "lines"}
            </span>
          </div>
          <Textarea
            ref={logsBox}
            id={`${id}-logs`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            wrap="off"
            rows={8}
            // The placeholder is an instruction in the sans, so the empty box never looks filled.
            className="font-mono text-xs leading-5 placeholder:font-sans placeholder:text-sm"
            placeholder="Paste log lines here, one per line."
            aria-invalid={touched && problem ? true : undefined}
            aria-describedby={`${id}-logs-hint`}
          />
          <p
            id={`${id}-logs-hint`}
            className={
              touched && problem
                ? "max-w-prose text-sm text-danger"
                : "max-w-prose text-sm text-muted-foreground"
            }
          >
            {logsHint(
              touched ? problem : null,
              publicDemo,
              (settings?.visitor_keys ?? []).length > 0,
              useLlm ? answers : "off",
            )}
          </p>
        </div>

        <div className="grid max-w-sm gap-2">
          <Label htmlFor={`${id}-system`}>What wrote these logs?</Label>
          <Select value={system} onValueChange={setSystem}>
            <SelectTrigger id={`${id}-system`} aria-describedby={`${id}-system-hint`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(SYSTEM_NAMES).map(([value, name]) => (
                <SelectItem key={value} value={value}>
                  {value === "generic" ? "Not sure" : name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* The named formats are the public datasets ARIA was tested on (J-m7). */}
          <p id={`${id}-system-hint`} className="text-sm text-muted-foreground">
            The named systems are the public logs ARIA was tested on. For anything else, such as a
            database, a web server or Kubernetes, choose Not sure: ARIA reads common formats.
          </p>
        </div>

        <details className="group rounded-lg bg-raised px-5 py-3">
          <summary className="cursor-pointer py-1 text-sm font-medium">Options</summary>
          <div className="grid gap-4 pt-3">
            <div className="grid gap-2">
              <Label htmlFor={`${id}-title`}>
                Title <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id={`${id}-title`}
                value={title}
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="ARIA writes one from the evidence if you leave this empty"
              />
            </div>
            <div className="grid">
              {/* With no model to answer, the switch shows off rather than on but unused (J-m8). */}
              <Toggle
                id={`${id}-llm`}
                label="Use a language model if one is set up"
                hint={llmHint}
                checked={useLlm && answers !== "offline"}
                onChange={setUseLlm}
                disabled={answers === "offline"}
              />
              <Toggle
                id={`${id}-investigate`}
                label="Investigate with tools"
                hint="Test likely causes with ARIA's read-only tools before writing the report."
                checked={investigate}
                onChange={setInvestigate}
              />
              <Toggle
                id={`${id}-approval`}
                label="Wait for my approval"
                hint={
                  approvalRequired
                    ? "This server always waits for a person before a report is published."
                    : "Off: the report publishes on its own, and no message is sent anywhere."
                }
                checked={approvalRequired || approval}
                onChange={setApproval}
                disabled={approvalRequired}
              />
            </div>
          </div>
        </details>

        {apiError ? (
          <p id={`${id}-api-error`} role="alert" className="text-sm text-danger">
            {apiError}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" size="lg" disabled={create.isPending}>
            {create.isPending ? "Starting" : "Start a triage"}
          </Button>
          <p className="text-sm text-muted-foreground">You can follow it live as it works.</p>
        </div>
        <p className="text-sm text-muted-foreground">
          Want alerts to start triages on their own?{" "}
          <Link href="/console/guide/connect" className="underline underline-offset-4">
            Connect ARIA to your systems
          </Link>
          .
        </p>
      </form>
    </div>
  );
}
