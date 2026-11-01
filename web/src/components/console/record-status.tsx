"use client";

import { ErrorState, LoadingRows } from "@/components/console/states";
import { useAuditVerify, type ChainCheckView } from "@/lib/api/hooks";
import { absoluteTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Whether the record holds, in a sentence: its length, or the first entry that breaks it. */
export function recordWords(check: ChainCheckView): string {
  const entries = check.length === 1 ? "one entry" : `${check.length.toLocaleString("en")} entries`;
  if (check.ok) {
    return check.length === 0
      ? "The decision record is empty: nothing has been decided yet."
      : `The decision record holds ${entries}, and every link in its chain verifies.`;
  }
  return `The decision record is broken at entry ${check.first_broken ?? "unknown"}: ${
    check.problem ?? "it does not verify"
  }. Treat that as a sign of tampering, and follow the ops runbook.`;
}

/** One line on whether the decision record verifies, from a fresh walk of the chain. */
export function RecordStatus() {
  const check = useAuditVerify();
  if (check.isPending) {
    return <LoadingRows rows={1} label="Checking the decision record" />;
  }
  if (check.isError) {
    return (
      <ErrorState
        title="The decision record could not be checked"
        error={check.error}
        onRetry={() => void check.refetch()}
      />
    );
  }
  const result = check.data;
  return (
    <div className="grid gap-1 text-sm">
      <p role="status" className={cn("max-w-prose", !result.ok && "font-medium text-danger")}>
        {recordWords(result)}
      </p>
      <p className="max-w-prose text-xs wrap-anywhere text-muted-foreground">
        Checked {absoluteTime(result.checked_at)}.
        {result.head_hash ? (
          <>
            {" "}
            Newest hash: <code className="font-mono">{result.head_hash}</code>. Keep it somewhere
            outside the database to notice a rewritten chain.
          </>
        ) : null}
      </p>
    </div>
  );
}
