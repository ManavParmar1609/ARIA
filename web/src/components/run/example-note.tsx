"use client";

import { CopyIcon, LoaderCircleIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { useFork, useHistory } from "@/lib/api/hooks";

// On a shared demo, an example is an incident every visitor sees, so nobody may review, send or
// delete it. In its place the page offers a copy of one's own: a fork from the moment the report
// waited for review, which reaches that point again in a few seconds and is private to this
// browser.

export function ExampleNote({ runId }: { runId: string }) {
  const router = useRouter();
  const history = useHistory(runId);
  const fork = useFork(runId);
  const starting = useRef(false);
  const [started, setStarted] = useState(false);
  // History is newest first: the latest moment the report waited for a person.
  const waiting = history.data?.find((cp) => cp.next.includes("review"));
  const busy = fork.isPending || started;

  const copy = () => {
    // A double click would make two copies before the first one's state reached the button.
    if (!waiting || starting.current) return;
    starting.current = true;
    fork.mutate(
      { checkpoint_id: waiting.checkpoint_id },
      {
        onSuccess: (accepted) => {
          setStarted(true);
          toast.success("Your copy is ready to review");
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
        onSettled: () => {
          starting.current = false;
        },
      },
    );
  };

  return (
    <section aria-labelledby="example-title" className="grid gap-3 rounded-lg bg-raised p-5">
      <h2 id="example-title" className="font-sans text-base font-semibold">
        This is an example
      </h2>
      <p className="max-w-prose text-sm text-muted-foreground">
        Every visitor sees it, so it stays as it is. To approve, edit or reject the report yourself,
        make your own copy. Only you can see it.
      </p>
      <Button
        variant="primary"
        className="justify-self-start"
        onClick={copy}
        disabled={busy || !waiting}
      >
        {busy ? (
          <LoaderCircleIcon aria-hidden className="size-4 animate-spin" />
        ) : (
          <CopyIcon aria-hidden />
        )}
        {busy ? "Making your copy" : "Make my own copy"}
      </Button>
      {history.isError ? (
        <ErrorState
          title="This example's checkpoints could not be loaded"
          error={history.error}
          onRetry={() => void history.refetch()}
        />
      ) : null}
      {fork.isError ? <ErrorState title="The copy could not be made" error={fork.error} /> : null}
    </section>
  );
}
