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
      "A log line with its changing parts (numbers, IDs, addresses) replaced by “…”, so thousands of lines collapse into a few patterns. ARIA finds them by grouping lines that differ only in those parts.",
  },
  pseudonymise: {
    term: "Pseudonymised",
    definition:
      "IP and e-mail addresses are replaced with a keyed hash before anything is stored or sent to a model. Lines from the same host still match each other, but the address itself never leaves.",
  },
  quarantine: {
    term: "Quarantined line",
    definition:
      "A log line that reads like an instruction to an AI model, such as 'ignore all previous instructions'. It is kept out of the analysis and shown to the person who reviews the incident. A language model writing the report sees it only as quoted text it is told not to follow.",
  },
  calibrated: {
    term: "Calibrated probability",
    definition:
      "A probability that means what it says: of all the windows ARIA rates 70% likely to be SEV2, about 70% really are SEV2.",
  },
  "prediction-set": {
    term: "Short list (prediction set)",
    definition:
      "The levels ARIA cannot rule out. Conformal prediction builds the list to hold the right level 90 times in 100 on incidents like the ones it was calibrated on; other logs can fall short. One level and a confident model: ARIA decides alone. Otherwise a model picks from the list, or a person decides.",
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
  runbook: {
    term: "Runbook",
    definition:
      "A team's written steps for one kind of problem, such as a disk filling up or a password-guessing attack: how to check it, fix it, confirm the fix and whom to call. ARIA proposes next steps only from runbooks, and cites the one it used.",
  },
  "on-call": {
    term: "On call",
    definition:
      "Taking a turn to answer alerts as they come in, often outside working hours. The person on call is who ARIA is for: it reads the logs so they do not have to read them line by line.",
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
    term: "Copy from an earlier step (fork)",
    definition:
      "A new incident that starts again from one of another incident's saved steps, with different options, so you can see what would have changed.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;
