const STANDARDS = [
  {
    name: "Model Context Protocol (MCP)",
    what: "Nine read-only tools with structured output (incident and runbook search, log templates, component timelines, node breakdowns, ticket history) over stdio and streamable HTTP. Any MCP client can use ARIA's memory.",
  },
  {
    name: "Agent2Agent (A2A)",
    what: "An agent card and JSON-RPC task endpoints, so another agent can hand ARIA a triage. The review pause maps to the input-required task state.",
  },
  {
    name: "AG-UI",
    what: "Runs stream as typed events: steps, tool calls, the report text and the review interrupt. CopilotKit and other AG-UI clients can drive a run and answer the review.",
  },
  {
    name: "LangGraph",
    what: "A checkpoint after every step: pause for review, survive a restart, rewind to any step and fork a new run with different options.",
  },
  {
    name: "OpenTelemetry",
    what: "GenAI semantic-convention traces for every model and tool call, exported over OTLP to Arize Phoenix, Langfuse or Jaeger, or to Azure Monitor.",
  },
  {
    name: "Open-weight models",
    what: "NVIDIA NIM, any OpenAI-compatible server, or Azure OpenAI. Switching provider is a configuration change; without one, ARIA runs deterministically.",
  },
];

export function Standards() {
  return (
    <dl className="grid gap-x-12 gap-y-8 md:grid-cols-2">
      {STANDARDS.map((s) => (
        <div key={s.name} className="grid content-start gap-2 border-t border-rule pt-4">
          <dt className="text-lg font-bold">{s.name}</dt>
          <dd className="text-muted-foreground">{s.what}</dd>
        </div>
      ))}
    </dl>
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
    <ul className="grid max-w-3xl gap-3">
      {LIMITS.map((item) => (
        <li key={item} className="grid grid-cols-[1.25rem_1fr] gap-2 text-muted-foreground">
          <span aria-hidden className="mt-2.5 block h-px w-3 bg-control" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}
