import type { Severity } from "@/lib/api/types";
import { LEVEL_RESPONSE, LEVEL_WORD } from "@/lib/levels";

// The words ARIA's pages use that a newcomer may not know, defined in plain English. The landing
// page, the console guide and Ask ARIA all read this list, so a term means the same thing
// everywhere. Keys are stable: other code looks entries up by them.

export interface GlossaryEntry {
  term: string;
  definition: string;
}

/** A severity level in the words the report and the incident page use (levels.ts). */
function level(severity: Severity, place: string): GlossaryEntry {
  return {
    term: `${severity} (${LEVEL_WORD[severity]})`,
    definition: `${place} ${LEVEL_RESPONSE[severity]}`,
  };
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
      "The levels ARIA cannot rule out, each kept on the list by a promise of its own: tighter for SEV1 and SEV2 than for SEV3 and SEV4, on incidents like those ARIA was calibrated on. One level and a confident model: ARIA decides alone. Otherwise a model picks from the list, or a person decides.",
  },
  "level-promise": {
    term: "Promise for each level",
    definition:
      "How often a short list is built to hold the right level, set separately for each level, so a rare serious incident is not left out to make common ones look good. It holds on incidents like those ARIA was calibrated on; blind checks tune it to yours.",
  },
  "novelty-check": {
    term: "Novelty check",
    definition:
      "Before deciding, ARIA asks whether the logs look like anything its model learned from. A window too far from the training data, with too many patterns new to its system, or from a system the model never saw is never decided alone: a person confirms it, and the short list widens to what the rules leave open.",
  },
  "impact-dimensions": {
    term: "Two kinds of impact",
    definition:
      "To call an incident SEV1, the rules that fired must show two different kinds of harm between them, such as an outage and how far it spreads, or data at risk and a critical part. One kind alone counts towards SEV2.",
  },
  "severe-miss": {
    term: "Severe miss",
    definition:
      "A serious incident (SEV1 or SEV2) rated minor (SEV3 or SEV4): the mistake that matters most. The short lists certify a limit on how often it happens, the tests report it first with an honest upper bound, and an alarm sounds when blind checks show more of them than promised.",
  },
  "safety-floor": {
    term: "Safety floor",
    definition:
      "A rule that sets the lowest severity a dangerous pattern can get, such as data loss or a security breach, whatever the model says.",
  },
  baseline: {
    term: "A system's usual error rate",
    definition:
      "The share of errors in a system's recent incidents. When a window's errors run many times above it, the way burn-rate alerts measure, a rule scores the window higher. It exists only once a system has been triaged a few times.",
  },
  "dismissed-pattern": {
    term: "Dismissed pattern",
    definition:
      "A log pattern that reviewers discarded before, or rated SEV4, on the same system. When most of a window's trouble lines follow one, the incident says so for the reviewer to weigh. It informs; it never lowers the level.",
  },
  critic: {
    term: "Critic",
    definition:
      "A second reading of the draft report that removes claims their evidence does not support, by another model where one is set up. When it cannot judge, it says so, and the reviewer sees what to check.",
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
      "Every report waits for a person. Nothing is posted to Slack, Teams, a ticket or a status page until a reviewer approves it, and each decision goes on the decision record.",
  },
  "blind-check": {
    term: "Blind check",
    definition:
      "A person rates a recent incident from its logs alone, before seeing ARIA's level. A rating given blind carries no pull to agree with ARIA, so these are what recalibrate its short lists; approvals no longer count. Settings has it under Check ARIA blind.",
  },
  drift: {
    term: "Drift",
    definition:
      "A shift in the levels ARIA decides for a system, its recent incidents against its earlier ones, beyond what chance explains. It needs no labels and says only that the mix has moved: new kinds of incident, a changed system or short lists that no longer fit. Settings asks “Has anything shifted?”.",
  },
  "decision-record": {
    term: "Decision record",
    definition:
      "An append-only list of every review, edit, publish, message sent, blind check, recalibration, model change, purge and deletion: who decided, what and when, never the logs themselves. Each entry is chained by a hash to the one before it, so any later change shows when the chain is verified.",
  },
  retention: {
    term: "Retention",
    definition:
      "How long incidents are kept: until someone deletes them, or, once an operator sets a period, until a purge deletes those older than it with everything that belongs only to them. The decision record keeps their entries.",
  },
  "model-pool": {
    term: "Model pool",
    definition:
      "One shared key serves several models, each with limits of its own on requests and tokens a minute and requests a day. Before every call ARIA gives the call to the best model with room; a triage reserves its calls first, and when none fit it is written offline, with a note saying when the model is back.",
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
  // How Test results scores a test, and what each test was tuned on.
  rings: {
    term: "Three rings",
    definition:
      "How ARIA is tested: fresh samples of the systems it learned from (a check for regressions), systems and kinds of failure it never saw (each held out in turn, the model fitted again without it), and real data with the labels its owners gave. Each test also records what was tuned on it.",
  },
  paged: {
    term: "Paged",
    definition:
      "Rated SEV1 or SEV2: serious enough to wake the person on call. Flagged means any rating from SEV1 to SEV3, worth a person's look but able to wait.",
  },
  auroc: {
    term: "Ranking score (AUROC)",
    definition:
      "How well a score puts the cases that matter above the rest: shown one of each, how often it ranks the right one higher. 0.5 is a coin flip and 1 is never wrong.",
  },
  "service-at-fault": {
    term: "Naming the service at fault",
    definition:
      "Pointing to the service a fault was put into. ARIA lists the services it suspects, likeliest first, and a test counts how often the right one comes first, or among the first three.",
  },
  interval: {
    term: "95% interval",
    definition:
      "The range a measured rate would most likely fall in on many more cases like these, with 95% confidence. A test with few cases gives a wide range.",
  },
  untouched: {
    term: "Untouched",
    definition:
      "A test whose results nobody looked at while ARIA was being changed, so they show how it does on data it was never fitted to.",
  },
  "looked-at": {
    term: "Looked at",
    definition:
      "A test whose results people saw while ARIA was being changed, though nothing was chosen by them. Still fair, but no longer untouched.",
  },
  tuned: {
    term: "Tuned",
    definition:
      "A test whose data was used to choose a change to ARIA, such as a rule or a threshold. Its results may flatter ARIA, so read them as a check rather than a clean test.",
  },
  // The four severity levels, most serious first.
  sev1: level("SEV1", "The most serious of ARIA's four severity levels."),
  sev2: level("SEV2", "The second of ARIA's four severity levels."),
  sev3: level("SEV3", "The third of ARIA's four severity levels."),
  sev4: level("SEV4", "The least serious of ARIA's four severity levels."),
  // The systems in the public logs ARIA is tested on, and their parts.
  hadoop: {
    term: "Hadoop",
    definition:
      "Free software that spreads very large amounts of data, and the jobs that work on it, over many servers so they act as one computer. HDFS is the part that stores the data.",
  },
  hdfs: {
    term: "HDFS",
    definition:
      "The Hadoop Distributed File System, where a Hadoop cluster keeps its data. It splits files into blocks and keeps copies of each on several servers, so one failing server loses nothing.",
  },
  datanode: {
    term: "DataNode",
    definition:
      "One of the servers in HDFS that store the blocks of data and hand them out when a program asks for them.",
  },
  openssh: {
    term: "OpenSSH",
    definition:
      "The software most servers use for SSH, the secure way to sign in to a computer over the network. Its log records every sign-in attempt, so password guessing shows up there.",
  },
  zookeeper: {
    term: "ZooKeeper",
    definition:
      "A small service that keeps a cluster's servers in agreement, such as on which one is in charge. When its servers lose touch with each other, everything built on it can stall.",
  },
  bluegene: {
    term: "BlueGene/L",
    definition:
      "A supercomputer built by IBM for Lawrence Livermore National Laboratory. Its public log, with alerts marked by the people who ran it, is a standard test for tools that read logs.",
  },
  lustre: {
    term: "Lustre",
    definition:
      "A file system that the computers of a supercomputer share, so thousands of them can read and write the same files at once.",
  },
  "io-node": {
    term: "I/O node",
    definition:
      "A computer inside a supercomputer that reads and writes data for the compute nodes, the computers that do the calculations.",
  },
  "kernel-panic": {
    term: "Kernel panic",
    definition:
      "A crash of the core of a computer's operating system. The computer stops at once and must restart, and whatever was running on it is lost.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;

/**
 * Where the glossary's words turn up in text that comes from data (an incident's title, a
 * sample's summary, the name of the system behind it), so a page can define them where they
 * stand. Matched as written, whole words only.
 */
export const GLOSSARY_WORDS: readonly (readonly [RegExp, GlossaryKey])[] = [
  [/\bHDFS\b/, "hdfs"],
  [/\bHadoop\b/, "hadoop"],
  [/\bDataNodes?\b/, "datanode"],
  [/\bOpenSSH\b/, "openssh"],
  [/\bZooKeeper\b/, "zookeeper"],
  [/\bBlueGene\/L\b/, "bluegene"],
  [/\bLustre\b/, "lustre"],
  [/\bI\/O nodes?\b/, "io-node"],
  [/\b[Kk]ernel panics?\b/, "kernel-panic"],
];

export interface GlossaryMention {
  start: number;
  end: number;
  key: GlossaryKey;
}

/**
 * The first mention of each glossary word in `text`, in reading order, leaving out the words in
 * `skip` (already defined nearby). One definition per word is plenty.
 */
export function glossaryMentions(
  text: string,
  skip: readonly GlossaryKey[] = [],
): GlossaryMention[] {
  const mentions: GlossaryMention[] = [];
  for (const [pattern, key] of GLOSSARY_WORDS) {
    if (skip.includes(key) || mentions.some((m) => m.key === key)) continue;
    const found = pattern.exec(text);
    if (!found) continue;
    const start = found.index;
    const end = start + found[0].length;
    // Two words can't share letters: "Hadoop" inside an earlier match stays plain.
    if (mentions.some((m) => start < m.end && end > m.start)) continue;
    mentions.push({ start, end, key });
  }
  return mentions.sort((a, b) => a.start - b.start);
}
