// How ARIA settled a severity, in words a newcomer can act on. Five cases come out of the severity
// engine and policy (src/aria/severity/engine.py, policy.py): a rule or safety floor set it; the
// model was confident in one level; the model saw one level but not confidently; several levels
// stayed possible; or no level was likely enough. A reviewer can also set it. Every incident still
// waits for a person before anything is sent, so a decided severity never means "done".

export interface Decision {
  severity: string;
  decided_by: string;
  prediction_set: readonly string[];
  set_empty?: boolean;
}

const ORDER = ["SEV1", "SEV2", "SEV3", "SEV4"];
const bySeverity = (a: string, b: string) => ORDER.indexOf(a) - ORDER.indexOf(b);

/** One sentence for how the severity was settled. */
export function decisionPhrase(d: Decision): string {
  switch (d.decided_by) {
    case "human":
      return "Set by a reviewer.";
    case "rules":
      return "Set by a rule.";
    case "model":
      return "Confident: decided by the model.";
  }
  if (d.set_empty) {
    return `No level was likely enough, so ARIA plans for ${d.severity}. Please decide.`;
  }
  const set = [...new Set(d.prediction_set)].sort(bySeverity);
  if (set.length > 1) {
    const list = `${set.slice(0, -1).join(", ")} or ${set.at(-1)}`;
    if (d.decided_by === "llm") {
      return `Could be ${list}. A language model chose ${d.severity} from that list.`;
    }
    const worst = set[0] === d.severity ? `${d.severity}, the most serious of them` : d.severity;
    return `Could be ${list}. ARIA plans for ${worst}. Please confirm.`;
  }
  if (d.decided_by === "llm") return `A language model chose ${d.severity}.`;
  return `Probably ${d.severity}, but ARIA is not sure enough to decide alone. Please confirm.`;
}

const SHORT: Record<string, string> = {
  rules: "Set by a rule",
  model: "Decided by the model",
  llm: "Chosen by a language model",
  fallback: "Needs your call",
  human: "Set by a reviewer",
};

/** A few words for lists, where only who decided is known. */
export function decidedByLabel(decidedBy: string | null | undefined): string {
  return decidedBy ? (SHORT[decidedBy] ?? decidedBy) : "";
}
