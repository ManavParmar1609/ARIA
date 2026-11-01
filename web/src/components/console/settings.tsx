"use client";

import { ChevronRightIcon, LogOutIcon } from "lucide-react";
import Link from "next/link";

import { BlindCheck, DriftReport } from "@/components/console/calibration-check";
import { DataTerms } from "@/components/console/data-terms";
import { ModelKeyPanel } from "@/components/console/model-key";
import { RecordStatus } from "@/components/console/record-status";
import { ReviewerStats } from "@/components/console/reviewer-stats";
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
  useCapacity,
  useFeedback,
  useModelKey,
  useProviders,
  useSession,
  useSettingsView,
  useSignOut,
  type CapacityView,
  type FeedbackView,
  type SettingsView,
} from "@/lib/api/hooks";
import { capacitySummary, dayWords, minuteWords, shownModels, stateWords } from "@/lib/capacity";
import { capitalise, money, percent, relativeTime, reviewerName } from "@/lib/format";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { accessSentence, modelAccess } from "@/lib/model-access";

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
        {intro ? <p className="max-w-prose text-sm text-muted-foreground">{intro}</p> : null}
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

/** "every hour", "every 6 hours", "every day": how often old runs are purged. */
function everyWords(seconds: number): string {
  const [size, unit] =
    seconds % 86_400 === 0
      ? [seconds / 86_400, "day"]
      : seconds % 3_600 === 0
        ? [seconds / 3_600, "hour"]
        : [Math.round(seconds / 60), "minute"];
  return size === 1 ? `every ${unit}` : `every ${size.toLocaleString("en")} ${unit}s`;
}

/** How long runs are kept (the retention period), in words. */
export function keptWords(retention: Record<string, number> | undefined): string {
  const days = retention?.days ?? 0;
  if (days <= 0) return "Until someone deletes them";
  const period = `${days.toLocaleString("en")} ${days === 1 ? "day" : "days"} after their last change`;
  const every = retention?.purge_interval_s ?? 0;
  return every > 0
    ? `${period}, purged ${everyWords(every)}`
    : `${period}, purged when someone runs aria purge`;
}

// The deployment's environment in words; "dev" is also what the free public demo runs as.
const ENVIRONMENT: Record<string, string> = {
  dev: "Development or demo",
  prod: "Production",
  test: "Test",
};

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
            ["Environment", ENVIRONMENT[view.environment] ?? view.environment],
            [
              "Reports wait for approval",
              view.require_approval ? "Yes" : "No, published automatically (nothing is sent)",
            ],
            [
              "Runs execute in",
              view.worker_mode === "external" ? "a separate worker" : "the API process",
            ],
            ["Requests a minute, for each caller", view.rate_limit_per_minute],
            ["Runs are kept", keptWords(view.retention)],
          ]}
        />
      </Section>
      <Section
        id="set-budgets"
        title="Budgets for each triage"
        intro="When a triage reaches a limit, the model steps stop and ARIA finishes without a model."
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
            ["Most lines in one triage", Number(g.max_lines).toLocaleString("en")],
          ]}
        />
      </Section>
      <Section id="set-decisions" title="Severity, retrieval and investigation">
        <Pairs
          items={[
            ["Short-list coverage", `${Math.round((1 - alpha) * 100)}%`],
            ["Similar incidents in one triage", r.k],
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

/** The room left on each of the site's models: this minute, today, and any rest. */
function SiteModels({ capacity }: { capacity: CapacityView }) {
  const models = shownModels(capacity);
  if (models.length === 0) {
    return (
      <p className="max-w-prose text-sm text-muted-foreground">
        No limits are set for this server&apos;s models, so ARIA does not count their requests.
      </p>
    );
  }
  return (
    <>
      <p role="status" className="max-w-prose text-sm">
        {capacitySummary(capacity)}
      </p>
      <Table aria-label="Room left on each of the site's models">
        <TableHeader>
          <TableRow>
            <TableHead>Model</TableHead>
            <TableHead>This minute</TableHead>
            <TableHead>Today</TableHead>
            <TableHead>State</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {models.map((m) => (
            <TableRow key={m.name}>
              <TableHead scope="row" className="font-mono text-xs">
                {m.model ?? m.name}
              </TableHead>
              <TableCell className="tabular">{minuteWords(m)}</TableCell>
              <TableCell className="tabular">{dayWords(m)}</TableCell>
              <TableCell
                className={cn(
                  "text-sm",
                  m.held_until ? "text-sev3-fg" : m.set_up ? "text-ok" : "text-faint",
                )}
              >
                {stateWords(m)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}

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
  reject: "Discarded",
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
          ...(c.per_level
            ? ([
                ["Learns from", "Blind checks, one at a time"],
                ["Blind checks so far", String(c.blind_checks ?? 0)],
                [
                  "Adjusted on",
                  c.adapted_on
                    ? `${c.adapted_on} blind ${c.adapted_on === 1 ? "check" : "checks"}`
                    : "Not yet (as trained)",
                ],
              ] as [string, React.ReactNode][])
            : ([
                [
                  "Recalibrated on",
                  c.recalibrated
                    ? `${c.reviews_in_model} reviewed incidents`
                    : "Not yet (as trained)",
                ],
                ["Reviews since then", `${c.pending} of ${c.recalibrate_after} needed`],
                [
                  "Coverage on reviewed incidents",
                  c.coverage_before != null && c.coverage_after != null
                    ? `${percent(c.coverage_before)} before, ${percent(c.coverage_after)} after`
                    : "Measured at the first recalibration",
                ],
              ] as [string, React.ReactNode][])),
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
                <TableCell>{capitalise(reviewerName(r.reviewer))}</TableCell>
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
  const capacity = useCapacity();
  const savedKey = useModelKey();
  const kinds = view.data?.visitor_keys ?? [];
  const { theme, setTheme } = useTheme();
  // When the API is down every section fails the same way: say so once, at the top when the
  // configuration failed (the model section needs it) or else where the first failure is, and
  // let that one "Try again" reload them all.
  const failed = view.isError
    ? "view"
    : capacity.isError
      ? "capacity"
      : providers.isError
        ? "providers"
        : feedback.isError
          ? "feedback"
          : null;
  const retryAll = () => {
    if (providers.isError) void providers.refetch();
    if (view.isError) void view.refetch();
    if (feedback.isError) void feedback.refetch();
    if (capacity.isError) void capacity.refetch();
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
        description="Which model answers your incidents and questions, and how the console looks."
      />

      <Section
        id="set-model-key"
        title="Language model"
        intro={
          kinds.length > 0
            ? "Use your own Claude, Gemini, OpenAI or NVIDIA key for the incidents you triage and the questions you ask. Your browser keeps it and sends it only with those requests; the server uses it for that work alone and never stores it."
            : "Which model writes your reports and answers here."
        }
      >
        {view.isError ? (
          failure("view", "Settings could not be loaded", view.error)
        ) : view.isPending ? (
          <LoadingRows rows={2} label="Loading the model settings" />
        ) : (
          <>
            <p role="status" className="max-w-prose text-sm">
              {accessSentence(
                modelAccess(savedKey.data?.provider ?? null, kinds, view.data.shared_model),
                kinds.length > 0,
                true,
              )}
            </p>
            {kinds.length > 0 || savedKey.data?.provider ? <ModelKeyPanel kinds={kinds} /> : null}
          </>
        )}
      </Section>

      <Section
        id="set-data-terms"
        title="What providers do with prompts"
        intro="What each model provider's own terms say it may do with the evidence ARIA sends it, and when someone last read them for ARIA. Terms nobody has read yet say Not verified."
      >
        {view.isError ? (
          <p className="text-sm text-muted-foreground">Not loaded: see the error above.</p>
        ) : view.isPending ? (
          <LoadingRows rows={2} label="Loading what providers do with prompts" />
        ) : (
          <DataTerms terms={view.data.data_terms ?? []} />
        )}
      </Section>

      {/* Only where the site has a model of its own: its room is what visitors share. */}
      {view.data?.shared_model ? (
        <Section
          id="set-site-models"
          title="The site's models"
          intro="The site's key spreads its work over several models, each with limits of its own. ARIA counts every request first and keeps a share of each limit spare, so no model is asked for more than it allows. When all of them are at their limits, triages run offline until there is room again."
        >
          {capacity.isPending ? (
            <LoadingRows rows={2} label="Loading the room left on the site's models" />
          ) : capacity.isError ? (
            failure("capacity", "The site's models could not be loaded", capacity.error)
          ) : (
            <SiteModels capacity={capacity.data} />
          )}
        </Section>
      ) : null}

      <Section id="set-session" title="Your session">
        <div className="flex flex-wrap items-center justify-between gap-4 text-sm">
          <p className="max-w-prose">
            {session.data?.signedIn
              ? `Signed in with the key named "${session.data.name}". Reviews you make are recorded under that name.`
              : session.data?.authRequired === false
                ? !view.data
                  ? "This server needs no key."
                  : view.data.visitor_scope
                    ? "This shared demo needs no key. The incidents you start are yours alone, kept with this browser, and the examples every visitor sees stay as they are."
                    : "This API is open: it needs no key. Set ARIA_API_KEYS to require one."
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

      <details className="group/deployment border-t border-rule pt-6">
        <summary className="flex w-fit cursor-pointer items-center gap-2 text-xl tracking-heading">
          Deployment details
          <ChevronRightIcon
            aria-hidden
            className="size-5 text-muted-foreground transition-transform duration-(--duration-quick) group-open/deployment:rotate-90 motion-reduce:transition-none"
          />
        </summary>
        <p className="mt-1 max-w-[65ch] text-sm text-muted-foreground">
          What this ARIA deployment is set up to do: its model providers, limits, guardrails and
          learning. The server reads them from config/aria.yaml and its environment variables.
        </p>
        <div className="mt-6 grid gap-8">
          <Section
            id="set-providers"
            title="Model providers"
            intro="A self-hosted NIM leads the chain, then Gemini, then hosted NIM, each once its key or endpoint is set. Keys are never shown."
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
                      <TableHead scope="row">
                        {/* The offline stand-in answers every step when no model is set up. */}
                        {p.name === "fake" ? "Offline, no model" : p.name}
                      </TableHead>
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
            <p className="text-sm text-muted-foreground">Not loaded: see the error above.</p>
          ) : (
            <Configuration view={view.data} />
          )}

          <Section
            id="set-record"
            title="Decision record"
            intro="Every review, edit, publish, message sent, blind check, recalibration and purge goes on an append-only record, each entry hash-chained to the one before it. A chain that verifies means no entry was changed, removed or reordered since it was written."
          >
            <RecordStatus />
          </Section>

          <Section
            id="set-blind"
            title="Check ARIA blind"
            intro="Rate a recent incident from its logs alone, before you see ARIA's level. A rating given without seeing ARIA's answer is free of the pull to agree with it, so these are the ratings ARIA recalibrates its short lists on, one at a time."
          >
            <BlindCheck />
          </Section>

          <Section
            id="set-drift"
            title="Has anything shifted?"
            intro="For each system, the levels ARIA decided on its recent runs against its earlier runs. A shift beyond what chance explains is worth a look: new kinds of incidents, a changed system, or short lists that no longer fit."
          >
            <DriftReport />
          </Section>

          <Section
            id="set-learning"
            title="Learning from reviews"
            intro={
              view.data?.visitor_scope
                ? "Every review records the severity a reviewer settled on. On this shared demo, reviews of your own incidents stay private. ARIA recalibrates on blind checks, not on approvals, which tend to agree with whatever ARIA said."
                : "Every review records the severity a reviewer settled on. ARIA recalibrates on blind checks, not on approvals, which tend to agree with whatever ARIA said."
            }
          >
            {feedback.isPending ? (
              <LoadingRows rows={3} label="Loading reviews" />
            ) : feedback.isError ? (
              failure("feedback", "Reviews could not be loaded", feedback.error)
            ) : (
              <Learning view={feedback.data} />
            )}
            <div className="grid gap-3 pt-2">
              <h3 className="text-lg">How each reviewer decides</h3>
              <ReviewerStats />
            </div>
          </Section>
        </div>
      </details>
    </div>
  );
}
