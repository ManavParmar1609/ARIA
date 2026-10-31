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

/**
 * One sentence for how the severity was settled. Given the run's status, a request to confirm
 * becomes what came of it once a person has reviewed the incident.
 */
export function decisionPhrase(d: Decision, status?: string): string {
  const approved = status === "published";
  const ended = approved || status === "rejected";
  const plans = ended ? "planned" : "plans";
  const ask = (verb: "confirm" | "decide") =>
    !ended ? ` Please ${verb}.` : approved ? " A reviewer confirmed it." : "";
  switch (d.decided_by) {
    case "human":
      return d.prediction_set.includes(d.severity)
        ? `A reviewer chose ${d.severity} from the short list.`
        : `A reviewer set ${d.severity}, outside ARIA's short list.`;
    case "rules":
      // A safety rule settled it or the rules and a confident model named the same level; a
      // floor the model disagreed with is worded by the panel, which knows the rule.
      return "Set by the rules, and the severity model agrees.";
    case "model":
      return "Confident: decided by the severity model.";
  }
  if (d.set_empty) {
    return `No level was likely enough, so ARIA ${plans} for ${d.severity}.${ask("decide")}`;
  }
  const set = [...new Set(d.prediction_set)].sort(bySeverity);
  if (set.length > 1) {
    const list = `${set.slice(0, -1).join(", ")} or ${set.at(-1)}`;
    if (d.decided_by === "llm") {
      return `Could be ${list}. A language model chose ${d.severity} from that list.`;
    }
    const worst = set[0] === d.severity ? `${d.severity}, the most serious of them` : d.severity;
    return `Could be ${list}. ARIA ${plans} for ${worst}.${ask("confirm")}`;
  }
  if (d.decided_by === "llm") return `A language model chose ${d.severity}.`;
  return `Only ${d.severity} is on the short list, but ARIA was not sure enough of it to decide alone.${ask("confirm")}`;
}

const SHORT: Record<string, string> = {
  rules: "Set by a rule",
  model: "Decided by the severity model",
  llm: "Chosen by a language model",
  fallback: "Needs your call",
  human: "Set by a reviewer",
};

/** A few words for lists, where only who decided is known. */
export function decidedByLabel(decidedBy: string | null | undefined): string {
  return decidedBy ? (SHORT[decidedBy] ?? decidedBy) : "";
}
