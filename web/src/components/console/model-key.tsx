"use client";

import { useId, useState, type FormEvent } from "react";

import { ErrorState, LoadingRows } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useForgetModelKey, useModelKey, useSaveModelKey } from "@/lib/api/hooks";
import { MODEL_KEYS, modelKeyLabel } from "@/lib/api/model-key";
import { cn } from "@/lib/utils";

/**
 * Save, use and forget a visitor's own model key. `kinds` are the kinds of key this ARIA takes
 * (none when it takes none, in which case a key saved earlier can still be forgotten).
 */
export function ModelKeyPanel({ kinds }: { kinds: string[] }) {
  const id = useId();
  const saved = useModelKey();
  const save = useSaveModelKey();
  const forget = useForgetModelKey();
  const [provider, setProvider] = useState(kinds[0] ?? "");
  const [key, setKey] = useState("");

  if (saved.isPending) return <LoadingRows rows={2} label="Loading your model key" />;
  if (saved.isError) {
    return (
      <ErrorState
        title="Your model key could not be read"
        error={saved.error}
        onRetry={() => void saved.refetch()}
      />
    );
  }

  if (saved.data.provider) {
    const usable = kinds.includes(saved.data.provider);
    return (
      <div className="flex flex-wrap items-center justify-between gap-4 text-sm">
        <p role="status">
          {usable
            ? `Runs you start and questions you ask use your ${modelKeyLabel(saved.data.provider)} key, ending in ${saved.data.ending}.`
            : "This server no longer takes visitors' own keys, so yours is not used."}
        </p>
        <Button size="sm" onClick={() => forget.mutate()} disabled={forget.isPending}>
          {forget.isPending ? "Forgetting…" : "Forget key"}
        </Button>
      </div>
    );
  }

  const chosen = MODEL_KEYS[provider];
  const refused =
    save.error?.message ?? (save.data && !save.data.accepted ? save.data.detail : null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(
      { provider, key },
      {
        onSuccess: (result) => {
          if (result.accepted) setKey("");
        },
      },
    );
  };

  return (
    <form className="grid max-w-xl gap-5" onSubmit={submit}>
      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium">Provider</legend>
        <div className="flex flex-wrap gap-2">
          {kinds.map((kind) => {
            const checked = provider === kind;
            return (
              <label
                key={kind}
                className={cn(
                  "relative inline-flex h-9 cursor-pointer items-center rounded-md border px-3 text-sm has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring",
                  checked
                    ? "border-primary bg-highlight font-medium text-highlight-foreground"
                    : "border-rule text-muted-foreground hover:text-foreground",
                )}
              >
                <input
                  type="radio"
                  name={`${id}-provider`}
                  value={kind}
                  checked={checked}
                  onChange={() => {
                    setProvider(kind);
                    save.reset();
                  }}
                  className="sr-only"
                />
                {modelKeyLabel(kind)}
              </label>
            );
          })}
        </div>
      </fieldset>
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-key`}>API key</Label>
        <Input
          id={`${id}-key`}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(event) => {
            setKey(event.target.value);
            if (save.data || save.error) save.reset();
          }}
          aria-invalid={refused ? true : undefined}
          aria-describedby={`${id}-key-hint${refused ? ` ${id}-key-error` : ""}`}
        />
        <p id={`${id}-key-hint`} className="text-sm text-muted-foreground">
          {chosen ? (
            <>
              Get one from{" "}
              <a
                href={chosen.href}
                target="_blank"
                rel="noreferrer"
                className="underline underline-offset-4"
              >
                {chosen.company}
              </a>
              . Choose a key you can revoke, with a spending limit.
            </>
          ) : (
            "Choose a key you can revoke, with a spending limit."
          )}
        </p>
        {refused ? (
          <p id={`${id}-key-error`} role="alert" className="text-sm text-danger">
            {refused}
          </p>
        ) : null}
      </div>
      <div>
        <Button type="submit" disabled={save.isPending || !provider || key.trim() === ""}>
          {save.isPending ? "Checking the key…" : "Check and save key"}
        </Button>
      </div>
    </form>
  );
}
