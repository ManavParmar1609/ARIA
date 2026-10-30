// What each graph step is called in the console. Plain data, so server-rendered pages
// (the evaluation page) and client components share it.
export const NODE_LABEL: Record<string, string> = {
  plan: "Plan",
  parse_shard: "Parse",
  merge: "Merge",
  severity: "Severity",
  recall: "Recall",
  investigate: "Investigate",
  assess: "Assess",
  widen: "Widen search",
  report: "Report",
  comms: "Messages",
  review: "Review",
  publish: "Publish",
  reject: "Reject",
};
