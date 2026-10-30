"use client";

import { LogOutIcon } from "lucide-react";
import Link from "next/link";

import { ErrorState, LoadingRows, PageHeader } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useFeedback,
  useProviders,
  useSession,
  useSettingsView,
  useSignOut,
  type FeedbackView,
  type SettingsView,
} from "@/lib/api/hooks";
import { money, percent, relativeTime } from "@/lib/format";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";

const THEMES: [ThemeChoice, string][] = [
  ["light", "Light"],
  ["dark", "Dark"],
  ["system", "Match my system"],
];

function Section({
  id,
  title,
  intro,
  children,
}: {
  id: string;
  title: string;
  intro?: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="grid gap-4 border-t border-rule pt-6">
      <div className="grid gap-1">
        <h2 id={id} className="text-xl tracking-heading">
          {title}
        </h2>
        {intro ? <p className="max-w-3xl text-sm text-muted-foreground">{intro}</p> : null}
      </div>
      {children}
    </section>
  );
}

function Pairs({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2 xl:grid-cols-3">
      {items.map(([label, value]) => (
        <div
          key={label}
          className="flex items-baseline justify-between gap-4 border-b border-rule/70 py-1.5"
        >
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="tabular text-right font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const onOff = (value: unknown) => (value ? "On" : "Off");

function Configuration({ view }: { view: SettingsView }) {
  const b = view.budgets as Record<string, number>;
  const g = view.guardrails as Record<string, unknown>;
  const r = view.retrieval as Record<string, number>;
  const inv = view.investigation as Record<string, number>;
  const alpha = Number((view.severity as Record<string, number>).alpha ?? 0.1);
  return (
    <>
      <Section id="set-run" title="Runs" intro="How runs are executed and reviewed.">
        <Pairs
          items={[
            ["Environment", view.environment],
            [
              "Reports wait for approval",
              view.require_approval ? "Yes" : "No, published automatically (nothing is sent)",
            ],
            [
              "Runs execute in",
              view.worker_mode === "external" ? "a separate worker" : "the API process",
            ],
            ["Requests per minute, per key", view.rate_limit_per_minute],
          ]}
        />
      </Section>
      <Section
        id="set-budgets"
        title="Budgets per run"
        intro="When a run reaches a limit, the LLM steps stop and ARIA finishes on the deterministic path."
      >
        <Pairs
          items={[
            ["Tokens", Number(b.max_tokens).toLocaleString("en")],
            ["Cost", money(b.max_cost_usd)],
            ["Wall-clock time", `${b.max_latency_s} s`],
            ["Graph steps", b.max_steps],
            ["Tool calls", b.max_tool_calls],
            ["Model calls", b.max_llm_calls],
          ]}
        />
      </Section>
      <Section
        id="set-guardrails"
        title="Guardrails"
        intro="Applied to every line before it is stored or shown to a model."
      >
        <Pairs
          items={[
            ["Redact secrets and personal data", onOff(g.redact_pii)],
            ["Pseudonymise IP addresses", onOff(g.pseudonymize_ips)],
            ["Quarantine prompt injection", onOff(g.detect_injection)],
            ["Content-safety model", onOff(g.safety_model)],
            ["Longest line kept", `${String(g.max_line_chars)} characters`],
            ["Most lines per run", Number(g.max_lines).toLocaleString("en")],
          ]}
        />
      </Section>
      <Section id="set-decisions" title="Severity, retrieval and investigation">
        <Pairs
          items={[
            ["Prediction-set coverage", `${Math.round((1 - alpha) * 100)}%`],
            ["Similar incidents per run", r.k],
            ["Candidates before reranking", r.candidates],
            ["Candidates when widened", r.widen_candidates],
            ["Retrieval attempts", r.max_attempts],
            ["Investigation tool calls", inv.max_steps],
            ["Investigation rounds", inv.max_rounds],
            ["Hypotheses at once", inv.max_hypotheses],
          ]}
        />
      </Section>
      <Section
        id="set-routing"
        title="Model routing"
        intro="Each role tries these providers in order; a provider without a key is skipped, and every chain but the adjudicator ends at the deterministic fallback."
      >
        <Table aria-label="Provider chain per role">
          <TableHeader>
            <TableRow>
              <TableHead className="w-64">Roles</TableHead>
              <TableHead>Providers, in order</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {chains(view.routing).map(([chain, roles]) => (
              <TableRow key={chain}>
                <TableHead scope="row">{roles.map((r) => ROLE[r] ?? r).join(", ")}</TableHead>
                <TableCell className="font-mono text-xs">{chain}</TableCell>
              </TableRow>
            ))}
            <TableRow>
              <TableHead scope="row">Embeddings</TableHead>
              <TableCell className="font-mono text-xs">{view.embeddings.join(" then ")}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </Section>
    </>
  );
}

// What each model role does, in the words the rest of the console uses.
const ROLE: Record<string, string> = {
  adjudicator: "Severity choice",
  investigator: "Investigator",
  reporter: "Report writer",
  critic: "Report critic",
  comms: "Message drafts",
  ask: "Ask ARIA",
  default: "Anything else",
};

/** Roles grouped by the chain they share, so each chain is written once. */
function chains(routing: Record<string, string[]>): [string, string[]][] {
  const byChain = new Map<string, string[]>();
  for (const [role, chain] of Object.entries(routing)) {
    const key = chain.join(" then ");
    byChain.set(key, [...(byChain.get(key) ?? []), role]);
  }
  return [...byChain];
}

const DECISION: Record<string, string> = {
  approve: "Approved",
  edit: "Edited",
  reject: "Rejected",
};

function Learning({ view }: { view: FeedbackView }) {
  const c = view.calibration;
  return (
    <>
      <Pairs
        items={[
          [
            "Severity model",
            <span key="model" className="font-mono text-xs">
              {c.model_version ?? "none"}
            </span>,
          ],
          [
            "Recalibrated on",
            c.recalibrated ? `${c.reviews_in_model} reviewed incidents` : "Not yet (as trained)",
          ],
          ["Reviews since then", `${c.pending} of ${c.recalibrate_after} needed`],
          [
            "Coverage on reviewed incidents",
            c.coverage_before != null && c.coverage_after != null
              ? `${percent(c.coverage_before)} before, ${percent(c.coverage_after)} after`
              : "Measured at the first recalibration",
          ],
          [
            "Checked",
            c.check_interval_s > 0
              ? `every ${Math.round(c.check_interval_s / 60)} min`
              : "Never (off)",
          ],
        ]}
      />
      {view.reviews.length ? (
        <Table aria-label="Recent reviews">
          <TableHeader>
            <TableRow>
              <TableHead>Run</TableHead>
              <TableHead>Decision</TableHead>
              <TableHead>Severity</TableHead>
              <TableHead>Reviewer</TableHead>
              <TableHead>When</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {view.reviews.map((r) => (
              <TableRow key={`${r.run_id}-${r.created_at}`}>
                <TableCell className="font-mono text-xs">
                  <Link
                    href={`/console/runs/${encodeURIComponent(r.run_id)}` as never}
                    className="underline decoration-control underline-offset-2 hover:decoration-foreground"
                  >
                    {r.run_id}
                  </Link>
                </TableCell>
                <TableCell>{DECISION[r.decision] ?? r.decision}</TableCell>
                <TableCell className="tabular">
                  {r.from_severity && r.to_severity && r.from_severity !== r.to_severity
                    ? `${r.from_severity} to ${r.to_severity}`
                    : (r.to_severity ?? "")}
                </TableCell>
                <TableCell>{r.reviewer}</TableCell>
                <TableCell className="text-muted-foreground">
                  {relativeTime(r.created_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <p className="text-sm text-muted-foreground">
          No reviews yet. Approve or edit a report and it is recorded here.
        </p>
      )}
    </>
  );
}

export function Settings() {
  const session = useSession();
  const signOut = useSignOut();
  const providers = useProviders();
  const view = useSettingsView();
  const feedback = useFeedback();
  const { theme, setTheme } = useTheme();
  // When the API is down every section fails the same way: say so once, in the first section
  // that failed, and let that one "Try again" reload them all.
  const failed = providers.isError
    ? "providers"
    : view.isError
      ? "view"
      : feedback.isError
        ? "feedback"
        : null;
  const retryAll = () => {
    if (providers.isError) void providers.refetch();
    if (view.isError) void view.refetch();
    if (feedback.isError) void feedback.refetch();
  };
  const failure = (key: string, title: string, error: unknown) =>
    failed === key ? (
      <ErrorState title={title} error={error} onRetry={retryAll} />
    ) : (
      <p className="text-sm text-muted-foreground">Not loaded: see the error above.</p>
    );

  return (
    <div className="grid gap-8">
      <PageHeader
        title="Settings"
        description="What this ARIA deployment is configured to do. Settings live in config/aria.yaml and environment variables, never in the browser."
      />

      <Section id="set-session" title="Your session">
        <div className="flex flex-wrap items-center justify-between gap-4 text-sm">
          <p>
            {session.data?.signedIn
              ? `Signed in with the key named "${session.data.name}". Reviews you make are recorded under that name.`
              : session.data?.authRequired === false
                ? "This API is open: it needs no key. Set ARIA_API_KEYS to require one."
                : "Not signed in."}
          </p>
          {session.data?.signedIn ? (
            <Button size="sm" onClick={() => signOut.mutate()}>
              <LogOutIcon aria-hidden />
              Sign out
            </Button>
          ) : null}
        </div>
        <fieldset className="grid gap-2">
          <legend className="mb-2 text-sm font-medium">Theme</legend>
          <div className="flex flex-wrap gap-2">
            {THEMES.map(([value, label]) => {
              const checked = theme === value;
              return (
                <label
                  key={value}
                  className={cn(
                    "relative inline-flex h-9 cursor-pointer items-center rounded-md border px-3 text-sm has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring",
                    checked
                      ? "border-primary bg-highlight font-medium text-highlight-foreground"
                      : "border-rule text-muted-foreground hover:text-foreground",
                  )}
                >
                  <input
                    type="radio"
                    name="theme"
                    value={value}
                    checked={checked}
                    onChange={() => setTheme(value)}
                    className="sr-only"
                  />
                  {label}
                </label>
              );
            })}
          </div>
        </fieldset>
      </Section>

      <Section
        id="set-providers"
        title="Model providers"
        intro="NVIDIA NIM leads the chain when NVIDIA_API_KEY is set. Keys are never shown."
      >
        {providers.isPending ? (
          <LoadingRows rows={3} label="Loading providers" />
        ) : providers.isError ? (
          failure("providers", "Providers could not be loaded", providers.error)
        ) : (
          <Table aria-label="Providers">
            <TableHeader>
              <TableRow>
                <TableHead>Provider</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Chat model</TableHead>
                <TableHead>Embeddings</TableHead>
                <TableHead>State</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {providers.data.map((p) => (
                <TableRow key={p.name}>
                  <TableHead scope="row">{p.name}</TableHead>
                  <TableCell className="text-muted-foreground">
                    {p.kind.replaceAll("_", " ")}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{p.chat_model ?? ""}</TableCell>
                  <TableCell className="font-mono text-xs">{p.embedding_model ?? ""}</TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        "text-sm",
                        !p.enabled
                          ? "text-faint"
                          : p.breaker === "closed"
                            ? "text-ok"
                            : "text-sev3-fg",
                      )}
                    >
                      {!p.enabled
                        ? "Not configured"
                        : p.breaker === "closed"
                          ? "Ready"
                          : `Circuit ${p.breaker.replace("_", "-")}`}
                    </span>
                    {p.last_error ? (
                      <span className="block text-xs text-danger">{p.last_error}</span>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      {view.isPending ? (
        <LoadingRows rows={4} label="Loading settings" />
      ) : view.isError ? (
        failure("view", "The configuration could not be loaded", view.error)
      ) : (
        <Configuration view={view.data} />
      )}

      <Section
        id="set-learning"
        title="Learning from reviews"
        intro="Every review records the severity a reviewer settled on. Once enough have gathered, ARIA recalibrates its prediction sets on them, so the sets hold the reviewer's severity on this deployment's own incidents."
      >
        {feedback.isPending ? (
          <LoadingRows rows={3} label="Loading reviews" />
        ) : feedback.isError ? (
          failure("feedback", "Reviews could not be loaded", feedback.error)
        ) : (
          <Learning view={feedback.data} />
        )}
      </Section>
    </div>
  );
}
