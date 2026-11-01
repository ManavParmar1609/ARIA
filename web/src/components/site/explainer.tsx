/**
 * The explainer video (item 28). It never plays on its own and loads only when someone presses
 * play. The list beneath it says what each part shows, always in view (owner request, round 9),
 * for anyone who would rather read; captions say the same while it plays.
 */
export function Explainer({ lines }: { lines: number }) {
  const parts = [
    `An alert fires, and ${lines} lines of logs arrive with it.`,
    "One line is an instruction, not a log. ARIA sets it aside: a reviewer sees it, the analysis never does.",
    "ARIA groups the lines into patterns and marks the ones new to this system.",
    "Rules and a calibrated model rate the severity and keep a short list of likely levels.",
    "An agent tests its ideas with tools that can only read, and finds the closest past incidents and the runbook they used.",
    "The report cites its evidence for every claim.",
    "The messages wait as drafts until a person approves them. Then the incident is published and joins ARIA's memory.",
    "The test results, caveats included.",
  ];
  return (
    <figure className="grid gap-6">
      <video
        controls
        preload="none"
        playsInline
        poster="/explainer-poster.jpg"
        width={1280}
        height={720}
        aria-label="ARIA explained in a short video"
        className="aspect-video h-auto w-full rounded-card bg-panel-slate"
      >
        <source src="/aria-explainer.mp4" type="video/mp4" />
        {/* The video has no soundtrack: these captions say what each part shows. */}
        <track kind="captions" src="/aria-explainer.vtt" srcLang="en" label="English" />
      </video>
      <figcaption className="grid gap-4">
        <p className="text-lg font-semibold text-heading">What the video shows</p>
        <ol className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          {parts.map((part, i) => (
            <li key={part} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3">
              <span
                aria-hidden
                className="tabular grid size-8 place-items-center rounded-full bg-panel-keylime text-sm font-semibold text-heading"
              >
                {i + 1}
              </span>
              <span className="pt-0.5 text-base leading-relaxed text-foreground">
                <span className="sr-only">{i + 1}. </span>
                {part}
              </span>
            </li>
          ))}
        </ol>
      </figcaption>
    </figure>
  );
}
