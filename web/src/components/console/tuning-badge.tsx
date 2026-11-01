import { Definable } from "@/components/aria/term";
import { GLOSSARY } from "@/lib/glossary";
import { tuningLabel, tuningTitle, type Tuning, type TuningStatus } from "@/lib/tuning";

const MEANING: Record<TuningStatus, string> = {
  untouched: GLOSSARY.untouched.definition,
  seen: GLOSSARY["looked-at"].definition,
  tuned: GLOSSARY.tuned.definition,
};

/** The status as a circle that fills the more a test's results were used; its name is beside it. */
function Mark({ status }: { status: TuningStatus }) {
  return (
    <svg aria-hidden viewBox="0 0 10 10" className="size-2.5 shrink-0 text-heading">
      <circle cx="5" cy="5" r="4.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
      {status === "seen" ? <path d="M5 0.75a4.25 4.25 0 0 1 0 8.5z" fill="currentColor" /> : null}
      {status === "tuned" ? <circle cx="5" cy="5" r="4.25" fill="currentColor" /> : null}
    </svg>
  );
}

/**
 * What a test's results were used for while ARIA was being changed (config/eval_registry.yaml): a
 * small badge whose card says what its status means and gives the record's note. It opens like a
 * dotted word, by click, Enter or Space, and Escape closes it. `context` names the test for screen
 * readers, so a list of the page's buttons tells the badges apart. `id` must be unique on the page.
 */
export function TuningBadge({
  id,
  tuning,
  context,
}: {
  id: string;
  tuning: Tuning;
  context: string;
}) {
  return (
    <Definable
      id={`tuning-${id}`}
      term={tuningTitle(tuning)}
      definition={
        <>
          <span className="block">{MEANING[tuning.status]}</span>{" "}
          {tuning.note ? (
            <span className="mt-3 block text-sm text-muted-foreground">{tuning.note}</span>
          ) : null}
        </>
      }
      className="inline-flex min-h-7 shrink-0 cursor-help items-center gap-1.5 rounded-full border border-rule bg-sunken px-2.5 text-xs font-medium text-muted-foreground transition-colors duration-(--duration-quick) hover:border-control hover:text-heading"
    >
      <Mark status={tuning.status} />
      <span className="underline decoration-primary/70 decoration-dotted underline-offset-[0.2em]">
        {tuningLabel(tuning)}
      </span>
      <span className="sr-only">: {context}</span>
    </Definable>
  );
}
