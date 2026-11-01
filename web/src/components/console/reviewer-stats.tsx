"use client";

import { ErrorState, LoadingRows } from "@/components/console/states";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useReviewers, type ReviewersView } from "@/lib/api/hooks";
import { absoluteTime, capitalise, count, duration, percent, reviewerName } from "@/lib/format";

/** "3 of 4 (75%)": how many of a reviewer's decisions, and what share. */
export function share(n: number, of: number): string {
  return of > 0
    ? `${n.toLocaleString("en")} of ${of.toLocaleString("en")} (${percent(n / of)})`
    : "";
}

/** Where the figures come from, in a sentence: every review kept, or the newest of them. */
export function readFrom(view: Pick<ReviewersView, "decisions" | "limit" | "since">): string {
  const reviews = view.decisions === 1 ? "review" : "reviews";
  const which =
    view.decisions >= view.limit
      ? `the ${count(view.decisions)} most recent ${reviews}`
      : `the ${count(view.decisions)} ${reviews}`;
  return `From ${which} ARIA keeps${view.since ? `, since ${absoluteTime(view.since)}` : ""}.`;
}

/** Each reviewer's figures, or a word on why there are none. */
export function ReviewerTable({ view }: { view: ReviewersView }) {
  if (view.reviewers.length === 0) {
    return (
      <p className="max-w-prose text-sm text-muted-foreground">
        No reviews yet. Once people approve, edit or discard reports, how each of them decides shows
        here.
      </p>
    );
  }
  return (
    <div className="grid gap-2">
      <Table aria-label="How each reviewer decides">
        <TableHeader>
          <TableRow>
            <TableHead>Reviewer</TableHead>
            <TableHead>Reviews</TableHead>
            <TableHead>Approved without edits</TableHead>
            <TableHead>Changed ARIA&apos;s level</TableHead>
            <TableHead>Median time to decide</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {view.reviewers.map((r) => (
            <TableRow key={r.reviewer}>
              <TableHead scope="row" className="wrap-anywhere">
                {capitalise(reviewerName(r.reviewer))}
              </TableHead>
              <TableCell className="tabular">{r.decisions.toLocaleString("en")}</TableCell>
              <TableCell className="tabular">{share(r.approved_as_is, r.decisions)}</TableCell>
              <TableCell className="tabular">{share(r.level_changed, r.decisions)}</TableCell>
              <TableCell className="tabular">
                {r.median_wait_s == null ? (
                  <span className="text-muted-foreground">Not known</span>
                ) : (
                  duration(r.median_wait_s * 1000)
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="max-w-prose text-xs text-muted-foreground">
        {readFrom(view)} The time to decide runs from when a report was ready for review to the
        decision. Reviews of deleted or purged incidents no longer count.
      </p>
    </div>
  );
}

/** How each reviewer decides: how often they approve without editing, how often they change
 * ARIA's level, and how long they take, from the reviews ARIA keeps. */
export function ReviewerStats() {
  const reviewers = useReviewers();
  if (reviewers.isPending) {
    return <LoadingRows rows={3} label="Loading how each reviewer decides" />;
  }
  if (reviewers.isError) {
    return (
      <ErrorState
        title="How each reviewer decides could not be loaded"
        error={reviewers.error}
        onRetry={() => void reviewers.refetch()}
      />
    );
  }
  return <ReviewerTable view={reviewers.data} />;
}
