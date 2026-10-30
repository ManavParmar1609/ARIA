"use client";

import { FileTextIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";

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
import samples from "@/data/samples.json";
import { ApiError } from "@/lib/api/client";
import { useCreateRun, useSettingsView } from "@/lib/api/hooks";
import { MAX_BODY_BYTES } from "@/lib/limits";
import { SYSTEM_NAMES } from "@/lib/systems";

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

const SNIPPETS = [
  {
    title: "From Alertmanager",
    body: "Add a webhook receiver; firing alerts that share a group key become one run.",
    code: "receivers:\n  - name: aria\n    webhook_configs:\n      - url: https://aria.example.com/api/v1/alerts/alertmanager\n        http_config:\n          authorization: { credentials: <api key> }",
  },
  {
    title: "From the command line",
    body: "Triage a log file end to end and print the report.",
    code: "aria triage /var/log/app.log --system hdfs",
  },
  {
    title: "From another agent",
    body: "ARIA is an A2A agent and an AG-UI agent; its MCP tools are read-only.",
    code: "GET /.well-known/agent-card.json\nPOST /a2a   (JSON-RPC)\nPOST /agui  (AG-UI events)\nPOST /mcp   (MCP, streamable HTTP)",
  },
];

/** The hint under the log box: what is wrong with the lines, else what happens to them. */
export function logsHint(problem: string | null, publicDemo: boolean): string {
  if (problem) return problem;
  return publicDemo
    ? "One event per line. This is a public demo: anyone can open the runs on it, so load a sample or paste only logs you can share."
    : "One event per line. IP and e-mail addresses are pseudonymised and secrets redacted before analysis or any model call; the lines you paste stay with the run until you delete it.";
}

export function NewRun({ publicDemo = false }: { publicDemo?: boolean }) {
  const id = useId();
  const router = useRouter();
  const create = useCreateRun();
  const [title, setTitle] = useState("");
  const [system, setSystem] = useState("generic");
  const [text, setText] = useState("");
  const [sample, setSample] = useState<string | null>(null);
  const [useLlm, setUseLlm] = useState(true);
  const [investigate, setInvestigate] = useState(true);
  const [approval, setApproval] = useState(true);
  const [touched, setTouched] = useState(false);
  // The server's rule wins: where it requires approval, every run waits for a person.
  const approvalRequired = useSettingsView().data?.require_approval ?? true;

  const lines = useMemo(() => text.split(/\r?\n/).filter((l) => l.trim()), [text]);
  // The lines' size as sent (UTF-8 JSON, with room for the other fields), so a paste the
  // console would refuse is caught before it is sent.
  const bytes = useMemo(
    () => new TextEncoder().encode(JSON.stringify(lines)).length + 2048,
    [lines],
  );
  const problem =
    lines.length === 0
      ? "Paste at least one log line, or load a sample."
      : lines.length > MAX_LINES
        ? `ARIA reads at most ${MAX_LINES.toLocaleString("en")} lines per run; this has ${lines.length.toLocaleString("en")}.`
        : bytes > MAX_BODY_BYTES
          ? `These lines come to ${(bytes / 1024 / 1024).toFixed(1)} MB; the console sends at most ${MAX_BODY_BYTES / 1024 / 1024} MB per run. Send fewer lines, or use the API or the CLI.`
          : null;
  const apiError = create.error instanceof ApiError ? create.error.detail : create.error?.message;

  const loadSample = (sampleId: string) => {
    const found = samples.find((s) => s.id === sampleId);
    if (!found) return;
    setSample(found.id);
    setSystem(found.system);
    setText(found.lines.join("\n"));
    setTitle("");
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (problem) return;
    create.mutate(
      {
        title: title.trim() || undefined,
        system,
        logs: lines,
        synthetic: sample !== null,
        options: { use_llm: useLlm, investigate, require_approval: approvalRequired || approval },
      },
      {
        onSuccess: (accepted) => {
          toast.success("Triage started", { description: "Following the run live." });
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
      },
    );
  };

  return (
    <div className="grid gap-8">
      <PageHeader
        title="New triage"
        description="Paste the logs around an incident. ARIA groups them into templates, rates severity, looks for similar past incidents, investigates and writes a cited report for you to review."
      />
      <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <form
          onSubmit={submit}
          className="grid gap-6"
          noValidate
          aria-describedby={apiError ? `${id}-api-error` : undefined}
        >
          <fieldset className="grid gap-2">
            <legend className="mb-2 text-sm font-medium">Start from a sample</legend>
            <div className="flex flex-wrap gap-2">
              {samples.map((s) => (
                <Button
                  key={s.id}
                  size="sm"
                  aria-pressed={sample === s.id}
                  className={
                    sample === s.id
                      ? "border-primary bg-highlight text-highlight-foreground"
                      : undefined
                  }
                  onClick={() => loadSample(s.id)}
                >
                  <FileTextIcon aria-hidden />
                  {s.label}
                </Button>
              ))}
            </div>
            <p className="text-sm text-muted-foreground">
              Samples are real Loghub lines arranged into a synthetic incident; runs from them are
              labelled synthetic.
            </p>
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_14rem]">
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
            <div className="grid gap-2">
              <Label htmlFor={`${id}-system`}>Log format</Label>
              <Select value={system} onValueChange={setSystem}>
                <SelectTrigger id={`${id}-system`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(SYSTEM_NAMES).map(([value, name]) => (
                    <SelectItem key={value} value={value}>
                      {name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

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
              onChange={(e) => {
                setText(e.target.value);
                setSample(null);
              }}
              spellCheck={false}
              wrap="off"
              rows={16}
              className="min-h-72 font-mono text-xs leading-5"
              placeholder={
                "081109 203615 148 INFO dfs.DataNode$PacketResponder: ...\n081109 203807 222 WARN dfs.DataNode$DataXceiver: ..."
              }
              aria-invalid={touched && problem ? true : undefined}
              aria-describedby={`${id}-logs-hint`}
            />
            <p
              id={`${id}-logs-hint`}
              className={
                touched && problem ? "text-sm text-danger" : "text-sm text-muted-foreground"
              }
            >
              {logsHint(touched ? problem : null, publicDemo)}
            </p>
          </div>

          <div className="grid">
            <Toggle
              id={`${id}-llm`}
              label="Use an LLM if one is configured"
              hint="Off: rules, the calibrated model and the grounded template only. Faster, and nothing leaves the server."
              checked={useLlm}
              onChange={setUseLlm}
            />
            <Toggle
              id={`${id}-investigate`}
              label="Investigate with tools"
              hint="Test hypotheses with ARIA's read-only MCP tools before writing the report."
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

          {apiError ? (
            <p id={`${id}-api-error`} role="alert" className="text-sm text-danger">
              {apiError}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" variant="primary" size="lg" disabled={create.isPending}>
              {create.isPending ? "Starting" : "Start triage"}
            </Button>
            <p className="text-sm text-muted-foreground">
              You can follow the run live as it works.
            </p>
          </div>
        </form>

        <aside aria-labelledby={`${id}-other`} className="grid content-start gap-4">
          <h2 id={`${id}-other`} className="font-sans text-base font-semibold">
            Other ways to start a run
          </h2>
          {SNIPPETS.map((s) => (
            <div key={s.title} className="grid gap-2 border-t border-rule pt-4">
              <h3 className="font-sans text-sm font-semibold">{s.title}</h3>
              <p className="text-sm text-muted-foreground">{s.body}</p>
              <pre
                tabIndex={0}
                role="region"
                aria-label={s.title}
                className="overflow-x-auto rounded-lg bg-sunken p-4 text-xs leading-5"
              >
                <code>{s.code}</code>
              </pre>
            </div>
          ))}
        </aside>
      </div>
    </div>
  );
}
