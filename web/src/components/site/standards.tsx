import { ArrowCircle } from "@/components/ui/button";
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
    why: "Why open-weight models",
    what: "NVIDIA NIM, any OpenAI-compatible server, or Azure OpenAI. Switching provider is a configuration change; without one, ARIA runs deterministically.",
    href: `${ADR}/0005-route-model-calls-through-provider-chains.md`,
  },
];

/** Text whose acronyms must not break at their hyphen ("AG-" then "UI" on the next line). */
const whole = (text: string) =>
  text.split(/\b(AG-UI|JSON-RPC)\b/).map((part, i) =>
    i % 2 === 1 ? (
      <span key={i} className="whitespace-nowrap">
        {part}
      </span>
    ) : (
      part
    ),
  );

/** The standards ARIA speaks, each linked to the decision record that explains it. */
export function Standards() {
  return (
    <ul className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
      {STANDARDS.map((s) => (
        <li
          key={s.name}
          className="group/button relative grid grid-rows-[auto_1fr_auto] gap-4 rounded-card border border-rule bg-raised p-7 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ring sm:p-9"
        >
          {/* Rows: name, text, link; the text row stretches, so links line up across a row. */}
          <h3 className="text-2xl leading-tight tracking-heading">{whole(s.name)}</h3>
          <p className="text-muted-foreground">{whole(s.what)}</p>
          {/* The whole card is the link's target; the words say where it goes. */}
          <a
            href={s.href}
            className="mt-1 inline-flex items-center gap-3 justify-self-start text-base font-medium text-heading outline-none after:absolute after:inset-0 after:rounded-card after:content-['']"
          >
            {/* One span: the link is a flex row, and loose text would gain its gap. */}
            <span>{"why" in s ? s.why : <>Why ARIA uses {whole(s.short)}</>}</span>
            <ArrowCircle size="md" />
          </a>
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
          <span aria-hidden className="mt-2 block size-2.5 rounded-full bg-sev2" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}
