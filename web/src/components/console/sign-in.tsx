"use client";

import { KeyRoundIcon } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { useSignIn } from "@/lib/api/hooks";

/** Sign in with an API key (one of the name:secret pairs in ARIA_API_KEYS). */
export function SignIn() {
  const id = useId();
  const [key, setKey] = useState("");
  const signIn = useSignIn();
  const error = signIn.error instanceof ApiError ? signIn.error.detail : signIn.error?.message;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (key.trim()) signIn.mutate(key.trim());
  };

  return (
    <section aria-labelledby={`${id}-title`} className="mx-auto grid max-w-md gap-6 py-10">
      <div className="grid gap-2">
        <KeyRoundIcon aria-hidden className="size-6 text-primary" />
        <h1 id={`${id}-title`} className="text-2xl tracking-heading">
          Sign in to the console
        </h1>
        <p className="text-muted-foreground">
          This ARIA API needs a key. Paste one of the secrets from its <code>ARIA_API_KEYS</code>{" "}
          setting; the key&apos;s name is recorded on the reviews you make.
        </p>
      </div>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <div className="grid gap-2">
          <Label htmlFor={`${id}-key`}>API key</Label>
          <Input
            id={`${id}-key`}
            type="password"
            autoComplete="current-password"
            spellCheck={false}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${id}-error` : `${id}-hint`}
            required
          />
          {error ? (
            <p id={`${id}-error`} role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : (
            <p id={`${id}-hint`} className="text-sm text-muted-foreground">
              The key stays on this server in an HTTP-only cookie for 12 hours. Page scripts never
              see it.
            </p>
          )}
        </div>
        <Button type="submit" variant="primary" disabled={!key.trim() || signIn.isPending}>
          {signIn.isPending ? "Checking the key" : "Sign in"}
        </Button>
      </form>
    </section>
  );
}
