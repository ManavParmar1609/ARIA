"use client";

import { GitForkIcon, HistoryIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { toast } from "sonner";

import { SeverityBadge } from "@/components/aria/severity";
import { ErrorState, LoadingRows } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api/client";
import { useFork, useHistory } from "@/lib/api/hooks";
import { isSeverity, type Checkpoint } from "@/lib/api/types";
import { clockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { NODE_LABEL } from "./activity";

function describe(cp: Checkpoint): string {
  if (cp.next.length === 0) return "The end of the run";
  if (cp.next.includes("__start__")) return "The input, before anything ran";
  const next = cp.next.map((n) => (NODE_LABEL[n] ?? n).toLowerCase());
  if (cp.interrupted) return `Paused before ${next.join(" and ")}`;
  return `Before ${next.join(" and ")}`;
}

/**
 * Time travel: every checkpoint of the run. Viewing one shows the run as it was then; forking
 * starts a new run from it, optionally with different options.
 */
export function History({
  runId,
  viewing,
  onView,
}: {
  runId: string;
  viewing: string | null;
  onView: (checkpoint: string | null) => void;
}) {
  const id = useId();
  const router = useRouter();
  const history = useHistory(runId);
  const fork = useFork(runId);
  const [forking, setForking] = useState<Checkpoint | null>(null);
  const [title, setTitle] = useState("");
  const [useLlm, setUseLlm] = useState(true);
  const [investigate, setInvestigate] = useState(true);
  const error = fork.error instanceof ApiError ? fork.error.detail : fork.error?.message;

  if (history.isPending) return <LoadingRows rows={4} label="Loading checkpoints" />;
  if (history.isError)
    return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  const items = history.data.filter((cp) => cp.next.length > 0 || cp.step != null);

  const startFork = () => {
    if (!forking) return;
    fork.mutate(
      {
        checkpoint_id: forking.checkpoint_id,
        title: title.trim() || undefined,
        options: { use_llm: useLlm, investigate },
      },
      {
        onSuccess: (accepted) => {
          setForking(null);
          toast.success("Fork started", { description: `New run ${accepted.run_id}` });
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
      },
    );
  };

  return (
    <div className="grid gap-4">
      <p className="max-w-prose text-sm text-muted-foreground">
        ARIA keeps a checkpoint after every step. View the run as it was at any of them, or fork a
        new run from one, for example to try it again with an LLM or without investigation.
      </p>
      <ol className="grid gap-1.5">
        {items.map((cp) => {
          const isViewing = viewing === cp.checkpoint_id;
          return (
            <li
              key={cp.checkpoint_id}
              className={cn(
                "flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2",
                isViewing ? "border-primary bg-highlight" : "border-rule",
              )}
            >
              <div className="grid min-w-0 gap-0.5">
                <p className="text-sm font-medium">
                  <span className="tabular mr-2 font-mono text-xs text-faint">
                    step {cp.step ?? "?"}
                  </span>
                  {describe(cp)}
                </p>
                <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {cp.created_at ? (
                    <time dateTime={cp.created_at}>{clockTime(cp.created_at)}</time>
                  ) : null}
                  {cp.source ? <span>{cp.source}</span> : null}
                  {isSeverity(cp.severity) ? (
                    <SeverityBadge severity={cp.severity} size="sm" />
                  ) : null}
                </p>
              </div>
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  variant={isViewing ? "primary" : "secondary"}
                  aria-pressed={isViewing}
                  onClick={() => onView(isViewing ? null : cp.checkpoint_id)}
                >
                  <HistoryIcon aria-hidden />
                  {isViewing ? "Viewing" : "View"}
                </Button>
                {cp.next.length > 0 && !cp.next.includes("__start__") ? (
                  <Button size="sm" onClick={() => setForking(cp)}>
                    <GitForkIcon aria-hidden />
                    Fork
                  </Button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      <Dialog open={forking !== null} onOpenChange={(open) => !open && setForking(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Fork a new run from this checkpoint</DialogTitle>
            <DialogDescription>
              {forking ? describe(forking) : ""}. The original run is not changed.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-title`}>
                Title <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id={`${id}-title`}
                value={title}
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor={`${id}-llm`}>Use an LLM if one is configured</Label>
              <Switch id={`${id}-llm`} checked={useLlm} onCheckedChange={setUseLlm} />
            </div>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor={`${id}-inv`}>Investigate with tools</Label>
              <Switch id={`${id}-inv`} checked={investigate} onCheckedChange={setInvestigate} />
            </div>
          </div>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button onClick={() => setForking(null)}>Cancel</Button>
            <Button variant="primary" onClick={startFork} disabled={fork.isPending}>
              {fork.isPending ? "Forking" : "Start the fork"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
