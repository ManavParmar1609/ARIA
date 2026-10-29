// The words ARIA's pages use that a newcomer may not know, defined in plain English. The landing
// page and the console guide both read this list, so a term means the same thing everywhere.

export interface GlossaryEntry {
  term: string;
  definition: string;
}

export const GLOSSARY = {
  "log-template": {
    term: "Log template",
    definition:
      "A log line with its changing parts (numbers, IDs, addresses) replaced by <*>, so thousands of lines collapse into a few patterns. ARIA mines them with the Drain algorithm.",
  },
  pseudonymise: {
    term: "Pseudonymised",
    definition:
      "IP and e-mail addresses are replaced with a keyed hash before anything is stored or sent to a model. Lines from the same host still match each other, but the address itself never leaves.",
  },
  quarantine: {
    term: "Quarantined line",
    definition:
      "A log line that reads like an instruction to an AI model, such as 'ignore all previous instructions'. It stays visible to people but is never used as evidence or sent to a model.",
  },
  calibrated: {
    term: "Calibrated probability",
    definition:
      "A probability that means what it says: of all the windows ARIA rates 70% likely to be SEV2, about 70% really are SEV2.",
  },
  "prediction-set": {
    term: "Prediction set",
    definition:
      "The severities ARIA cannot rule out, built by conformal prediction so that it holds the true severity 90% of the time. One severity in the set: ARIA decides alone. More than one: a model may choose among them, or ARIA takes the most severe and asks a person.",
  },
  "safety-floor": {
    term: "Safety floor",
    definition:
      "A rule that sets the lowest severity a dangerous pattern can get, such as data loss or a security breach, whatever the model says.",
  },
  evidence: {
    term: "Evidence ID",
    definition:
      "Every log line, template, rule, past incident or tool result ARIA used gets an ID such as E12. Each claim in a report cites the IDs it rests on, and a validator rejects any claim whose citation is missing or disagrees with the evidence.",
  },
  mcp: {
    term: "MCP tools",
    definition:
      "Model Context Protocol: the open standard ARIA's investigator uses to call its tools. All of them only read, and other agents can use the same tools to search ARIA's memory.",
  },
  replan: {
    term: "Replan",
    definition:
      "When no hypothesis holds up or the past matches look weak, ARIA widens its search and investigates again, at most twice.",
  },
  review: {
    term: "Review",
    definition:
      "Every report waits for a person. Nothing is posted to Slack, Teams, a ticket or a status page until a reviewer approves it.",
  },
  checkpoint: {
    term: "Checkpoint",
    definition:
      "A saved snapshot of the run after every step. It lets a run pause for review, carry on after a restart, or be rewound to any step.",
  },
  fork: {
    term: "Fork",
    definition:
      "A new run started from a past checkpoint of another run, with different options, so you can see what would have changed.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;
