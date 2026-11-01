import type { components } from "@/lib/api/schema";

export type DataTermsView = components["schemas"]["DataTermsOut"];
type DataUse = components["schemas"]["DataUseOut"];

const NOT_VERIFIED = "Not verified";

/** Whether the provider may use prompts to improve its models, as its terms say. */
export function improvesWords(use: Pick<DataUse, "improves_models">): string {
  if (use.improves_models == null) return NOT_VERIFIED;
  return use.improves_models ? "Yes, it may" : "No";
}

/** How long the provider keeps prompts, as its terms say. */
export function keepsWords(use: Pick<DataUse, "keeps_prompts">): string {
  return use.keeps_prompts ?? NOT_VERIFIED;
}

/** "Read on 1 November 2026", or "Not verified" for terms nobody has read for ARIA. */
export function readWords(verified: string | null | undefined): string {
  if (!verified) return NOT_VERIFIED;
  // A calendar date: shown as written, whatever the reader's time zone.
  const day = new Date(`${verified}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  return `Read on ${day}`;
}

/** What each model provider's own terms say about the prompts ARIA sends it, in plain words,
 * with when someone read them for ARIA. Terms nobody has read say "Not verified" throughout. */
export function DataTerms({ terms }: { terms: DataTermsView[] }) {
  if (terms.length === 0) {
    return (
      <p className="max-w-prose text-sm text-muted-foreground">
        This server&apos;s configuration records no provider terms.
      </p>
    );
  }
  return (
    <ul className="grid gap-5">
      {terms.map((entry) => (
        <li
          key={entry.id}
          className="grid gap-2 border-t border-rule/70 pt-4 first:border-0 first:pt-0"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h3 className="text-base">
              {entry.company}, {entry.service}
            </h3>
            <span
              className={
                entry.verified ? "text-sm text-muted-foreground" : "text-sm font-medium text-faint"
              }
            >
              {readWords(entry.verified)}
            </span>
          </div>
          {entry.providers.length ? (
            <p className="text-xs text-muted-foreground">
              ARIA&apos;s providers on these terms:{" "}
              <span className="font-mono">{entry.providers.join(", ")}</span>
            </p>
          ) : null}
          {entry.uses.map((use) => (
            <div key={use.account} className="grid gap-1">
              <p className="text-sm font-medium">{use.account}</p>
              <dl className="grid gap-1 text-sm sm:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] sm:gap-x-6">
                <dt className="text-muted-foreground">Uses prompts to improve its models</dt>
                <dd>{improvesWords(use)}</dd>
                <dt className="text-muted-foreground">Keeps prompts</dt>
                <dd className="max-w-prose">{keepsWords(use)}</dd>
              </dl>
            </div>
          ))}
          {entry.notes ? (
            <p className="max-w-prose text-xs text-muted-foreground">{entry.notes}</p>
          ) : null}
          <p className="text-sm">
            {entry.sources.length === 1 ? "Source: " : "Sources: "}
            {entry.sources.map((source, i) => (
              <span key={source.url}>
                {i > 0 ? ", " : null}
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline decoration-control underline-offset-2 hover:decoration-foreground"
                >
                  {source.title}
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
              </span>
            ))}
          </p>
        </li>
      ))}
    </ul>
  );
}
