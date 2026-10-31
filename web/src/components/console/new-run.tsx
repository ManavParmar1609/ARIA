"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useId, useMemo, useState, type FormEvent } from "react";

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
import { SYSTEM_NAMES } from "@/lib/systems";
import { accessSentence, modelAccess, type SharedModel } from "@/lib/model-access";

const MAX_LINES = 20_000;

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

/** The hint under the log box: what is wrong with the lines, else what happens to them. A model
 * key is mentioned only where this server accepts visitors' own keys. */
export function logsHint(problem: string | null, publicDemo: boolean, keys = false): string {
  if (problem) return problem;
  const model = keys ? " If you add a model key, they are sent to that model too." : "";
  return publicDemo
    ? `One event per line. Your logs stay with your incident, and only you see it, but this public demo runs on a shared server: paste only logs you could share.${model}`
    : `One event per line. Your logs stay with your incident until you delete it, with IP and e-mail addresses pseudonymised and secrets redacted.${model}`;
}

/** What the model switch does here: whose model answers when it is on, and what off means. */
export function modelHint(
  kinds: string[],
  savedProvider: string | null,
  shared?: SharedModel | null,
): string {
  const off = "Off: rules, the calibrated model and the grounded template only.";
  const access = modelAccess(savedProvider, kinds, shared);
  if (access.kind === "own") {
    return `On: your own ${modelKeyLabel(savedProvider ?? "")} key answers first. ${off}`;
  }
  if (access.kind === "shared") {
    return access.left == null
      ? `On: the site's key answers. ${off}`
      : `On: the site's key answers (shared, limited: ${access.left} left today). ${off}`;
  }
  if (access.usedUp) return accessSentence(access, kinds.length > 0);
  if (kinds.length > 0) return `${off} To use a model, add your own key in Settings.`;
  return `${off} Faster, and nothing leaves the server.`;
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
    router.replace((qs ? `${pathname}?${qs}` : pathname) as never, { scroll: false });
  };
  return (
    <div className="grid gap-8">
      <PageHeader
        title="New triage"
        description="Pick a sample to triage, or paste your own logs. ARIA reads them, rates how serious the incident is and drafts a report with its sources, and nothing is sent until you approve it."
      />
      <Tabs value={tab} onValueChange={setTab} className="grid gap-8">
        <TabsList aria-label="What to triage">
          <TabsTrigger value="samples">Samples</TabsTrigger>
          <TabsTrigger value="own">Your own logs</TabsTrigger>
        </TabsList>
        <TabsContent value="samples">
          <SampleGallery />
        </TabsContent>
        <TabsContent value="own">
          <OwnLogs publicDemo={publicDemo} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function OwnLogs({ publicDemo }: { publicDemo: boolean }) {
  const id = useId();
  const router = useRouter();
  const create = useCreateRun();
  const [title, setTitle] = useState("");
  const [system, setSystem] = useState("generic");
  const [text, setText] = useState("");
  const [useLlm, setUseLlm] = useState(true);
  const [investigate, setInvestigate] = useState(true);
  const [approval, setApproval] = useState(true);
  const [touched, setTouched] = useState(false);
  // The server's rule wins: where it requires approval, every run waits for a person.
  const settings = useSettingsView().data;
  const approvalRequired = settings?.require_approval ?? true;
  const savedKey = useModelKey().data;
  const llmHint = modelHint(
    settings?.visitor_keys ?? [],
    savedKey?.provider ?? null,
    settings?.shared_model,
  );

  const lines = useMemo(() => text.split(/\r?\n/).filter((l) => l.trim()), [text]);
  // The lines' size as sent (UTF-8 JSON, with room for the other fields), so a paste the
  // console would refuse is caught before it is sent.
  const bytes = useMemo(
    () => new TextEncoder().encode(JSON.stringify(lines)).length + 2048,
    [lines],
  );
  const problem =
    lines.length === 0
      ? "Paste at least one log line, or pick a sample on the Samples tab."
      : lines.length > MAX_LINES
        ? `ARIA reads at most ${MAX_LINES.toLocaleString("en")} lines per run; this has ${lines.length.toLocaleString("en")}.`
        : bytes > MAX_BODY_BYTES
          ? `These lines come to ${(bytes / 1024 / 1024).toFixed(1)} MB; the console sends at most ${MAX_BODY_BYTES / 1024 / 1024} MB per run. Send fewer lines, or use the API or the CLI.`
          : null;
  const apiError = create.error instanceof ApiError ? create.error.detail : create.error?.message;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (problem) return;
    create.mutate(
      {
        title: title.trim() || undefined,
        system,
        logs: lines,
        options: { use_llm: useLlm, investigate, require_approval: approvalRequired || approval },
      },
      {
        onSuccess: (accepted) => {
          // The incident page shows the run starting; no toast needs to say so (item 34).
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
      },
    );
  };

  return (
    <div className="grid max-w-4xl gap-10">
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
            id={`${id}-logs`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            wrap="off"
            rows={8}
            className="font-mono text-xs leading-5"
            placeholder={
              "081109 203615 148 INFO dfs.DataNode$PacketResponder: ...\n081109 203807 222 WARN dfs.DataNode$DataXceiver: ..."
            }
            aria-invalid={touched && problem ? true : undefined}
            aria-describedby={`${id}-logs-hint`}
          />
          <p
            id={`${id}-logs-hint`}
            className={touched && problem ? "text-sm text-danger" : "text-sm text-muted-foreground"}
          >
            {logsHint(
              touched ? problem : null,
              publicDemo,
              (settings?.visitor_keys ?? []).length > 0,
            )}
          </p>
        </div>

        <div className="grid max-w-sm gap-2">
          <Label htmlFor={`${id}-system`}>What wrote these logs?</Label>
          <Select value={system} onValueChange={setSystem}>
            <SelectTrigger id={`${id}-system`}>
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
              <Toggle
                id={`${id}-llm`}
                label="Use a language model if one is set up"
                hint={llmHint}
                checked={useLlm}
                onChange={setUseLlm}
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
