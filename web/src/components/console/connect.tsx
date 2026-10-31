import Link from "next/link";

import { AguiChat } from "@/components/console/agui-chat";
import { PageHeader } from "@/components/console/states";
import { CopyButton } from "@/components/ui/copy-button";

// For people who run ARIA themselves: the ways alerts, logs and other tools reach it, and where
// its messages go. Visitors to the public demo can read this but not set it up.

const WAYS: { id: string; title: string; body: string; code: string; label: string }[] = [
  {
    id: "alerts",
    title: "Start a triage when an alert fires",
    body: "Point Alertmanager or Grafana at ARIA. Alerts that fire together, with the same group key, become one incident.",
    label: "Alertmanager receiver",
    code: "receivers:\n  - name: aria\n    webhook_configs:\n      - url: https://aria.example.com/api/v1/alerts/alertmanager\n        http_config:\n          authorization: { credentials: <api key> }",
  },
  {
    id: "command-line",
    title: "Triage a log file from the command line",
    body: "ARIA reads the file, triages it end to end and prints the report.",
    label: "Command line",
    code: "aria triage /var/log/app.log --system hdfs",
  },
  {
    id: "agents",
    title: "Let other agents ask ARIA",
    body: "ARIA answers other AI agents through open protocols: A2A to hand it work, AG-UI to follow a triage live, and MCP for read-only tools that can look things up but never change them.",
    label: "Agent addresses",
    code: "GET /.well-known/agent-card.json\nPOST /a2a   (A2A, JSON-RPC)\nPOST /agui  (AG-UI events)\nPOST /mcp   (MCP, streamable HTTP)",
  },
  {
    id: "channels",
    title: "Send approved messages to Slack, Teams or a webhook",
    body: "ARIA drafts every message and sends it only after a person approves it. Without a channel it keeps them as previews. Set a channel's webhook address on the server to send them for real.",
    label: "Channel settings",
    code: "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...\nTEAMS_WEBHOOK_URL=https://...\nARIA_OUTBOUND_WEBHOOK_URL=https://...   # status page, tickets, anything else",
  },
];

export function Connect() {
  return (
    <div className="grid max-w-3xl gap-10">
      <PageHeader
        title="Connect ARIA to your systems"
        description="For people who run ARIA themselves. On the public demo you can read how it works, but these settings are not open."
      />
      {WAYS.map((way) => (
        <section
          key={way.id}
          id={way.id}
          aria-labelledby={`${way.id}-title`}
          className="grid gap-3"
        >
          <h2 id={`${way.id}-title`} className="font-sans text-lg font-semibold">
            {way.title}
          </h2>
          <p className="max-w-prose text-muted-foreground">{way.body}</p>
          <div className="grid overflow-hidden rounded-lg border border-rule bg-raised">
            <div className="flex items-center justify-between gap-3 border-b border-rule py-1 pr-1.5 pl-4">
              <span className="text-xs text-muted-foreground">{way.label}</span>
              <CopyButton text={way.code} label={`the ${way.label.toLowerCase()}`} />
            </div>
            <pre
              tabIndex={0}
              role="region"
              aria-label={way.label}
              className="overflow-x-auto p-4 text-[0.8125rem] leading-6 max-sm:break-all max-sm:whitespace-pre-wrap"
            >
              <code>{way.code}</code>
            </pre>
          </div>
        </section>
      ))}
      <section aria-labelledby="agui-title" className="grid gap-3">
        <h2 id="agui-title" className="font-sans text-lg font-semibold">
          Try it: follow a triage over AG-UI
        </h2>
        <AguiChat />
      </section>
      <section aria-labelledby="model-title" className="grid gap-3">
        <h2 id="model-title" className="font-sans text-lg font-semibold">
          Use a language model
        </h2>
        <p className="max-w-prose text-muted-foreground">
          ARIA triages offline by default. To have a model investigate and write the report, give
          the server a Claude, Gemini, OpenAI or NVIDIA key; the settings are listed in{" "}
          <code>.env.example</code>. Where a server also accepts visitors&apos; own keys,{" "}
          <Link href="/console/settings" className="underline underline-offset-4">
            Settings
          </Link>{" "}
          has a place for yours.
        </p>
      </section>
    </div>
  );
}
