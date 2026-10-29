import { ArrowUpRightIcon } from "lucide-react";

import { REPO_URL } from "@/lib/site-data";

const ADR = `${REPO_URL}/blob/main/docs/adr`;

const STANDARDS = [
  {
    name: "Model Context Protocol",
    short: "MCP",
    what: "Nine read-only tools with structured output (incident and runbook search, log templates, component timelines, node breakdowns, ticket history) over stdio and streamable HTTP. Any MCP client can use ARIA's memory.",
    href: `${ADR}/0006-call-mcp-tools-through-an-allowlisted-tool-belt.md`,
  },
  {
    name: "Agent2Agent",
    short: "A2A",
    what: "An agent card and JSON-RPC task endpoints, so another agent can hand ARIA a triage. The review pause maps to the input-required task state.",
    href: `${ADR}/0009-speak-a2a-ag-ui-and-mcp.md`,
  },
  {
    name: "AG-UI",
    short: "AG-UI",
    what: "Runs stream as typed events: steps, tool calls, the report text and the review interrupt. CopilotKit and other AG-UI clients can drive a run and answer the review.",
    href: `${ADR}/0009-speak-a2a-ag-ui-and-mcp.md`,
  },
  {
    name: "LangGraph",
    short: "LangGraph",
    what: "A checkpoint after every step: pause for review, survive a restart, rewind to any step and fork a new run with different options.",
    href: `${ADR}/0001-one-langgraph-graph-of-specialist-nodes.md`,
  },
  {
    name: "OpenTelemetry",
    short: "OpenTelemetry",
    what: "GenAI semantic-convention traces for every model and tool call, exported over OTLP to Arize Phoenix, Langfuse or Jaeger, or to Azure Monitor.",
    href: `${REPO_URL}/blob/main/docs/ops-runbook.md`,
  },
  {
    name: "Open-weight models",
    short: "models",
    what: "NVIDIA NIM, any OpenAI-compatible server, or Azure OpenAI. Switching provider is a configuration change; without one, ARIA runs deterministically.",
    href: `${ADR}/0005-route-model-calls-through-provider-chains.md`,
  },
];

/** The standards ARIA speaks, each linked to the decision record that explains it. */
export function Standards() {
  return (
    <ul className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
      {STANDARDS.map((s) => (
        <li
          key={s.name}
          className="relative grid content-start gap-3 rounded-lg bg-raised p-6 transition-colors duration-(--duration-quick) focus-within:ring-2 focus-within:ring-ring hover:bg-raised/80 sm:p-9"
        >
          <div className="flex items-start justify-between gap-4">
            <h3 className="text-xl leading-tight tracking-heading">{s.name}</h3>
            <a
              href={s.href}
              aria-label={`Why ARIA uses ${s.short}`}
              className="inline-flex size-8 shrink-0 items-center justify-center rounded-sm bg-foreground/8 text-heading outline-none after:absolute after:inset-0 after:rounded-lg after:content-['']"
            >
              <ArrowUpRightIcon aria-hidden className="size-4" strokeWidth={1.5} />
            </a>
          </div>
          <p className="text-muted-foreground">{s.what}</p>
        </li>
      ))}
    </ul>
  );
}

const LIMITS = [
  "Severity labels for most windows come from the scenario generator, not from people. Only BlueGene/L uses real alert tags.",
  "Incident memory ships synthetic. Retrieval looks perfect on it and will not on your own history.",
  "With a hosted model a run takes minutes. The fast numbers above are the offline path.",
  "The injection guard matches patterns. It is a first line of defence, not a proof: anything it misses reaches a model only as fenced, untrusted evidence.",
  "ARIA triages and drafts. It does not remediate, and it sends nothing without approval.",
];

export function Limitations() {
  return (
    <ul className="grid max-w-4xl rounded-lg bg-sunken px-6 py-2 sm:px-9">
      {LIMITS.map((item) => (
        <li
          key={item}
          className="grid grid-cols-[1.25rem_1fr] gap-3 border-b border-rule py-5 text-muted-foreground last:border-b-0"
        >
          <span aria-hidden className="mt-2.5 block h-px w-3 bg-primary/70" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}
