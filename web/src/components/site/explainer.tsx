/**
 * The explainer video (item 28). It has no sound, never plays on its own and loads only when
 * someone presses play. Captions and the list beneath say what each part shows, for anyone who
 * can't watch it.
 */
export function Explainer({ lines }: { lines: number }) {
  return (
    <figure className="grid max-w-4xl gap-3">
      <video
        controls
        preload="none"
        playsInline
        poster="/explainer-poster.jpg"
        width={1280}
        height={720}
        aria-label="ARIA explained in a short video, without sound"
        className="aspect-video h-auto w-full rounded-card bg-panel-slate"
      >
        <source src="/aria-explainer.mp4" type="video/mp4" />
        {/* The video has no sound: these captions say what each part shows. */}
        <track kind="captions" src="/aria-explainer.vtt" srcLang="en" label="English" />
      </video>
      <figcaption>
        <details>
          <summary className="w-fit cursor-pointer py-0.5 text-sm font-medium text-heading underline decoration-control underline-offset-4">
            What the video shows (it has no sound)
          </summary>
          <ol className="mt-3 grid max-w-[62ch] list-decimal gap-1.5 pl-5 text-sm leading-relaxed text-muted-foreground">
            <li>An alert fires, and {lines} lines of logs arrive with it.</li>
            <li>
              One line is an instruction, not a log. ARIA sets it aside: a reviewer sees it, the
              analysis never does.
            </li>
            <li>ARIA groups the lines into templates and marks the ones new to this system.</li>
            <li>
              Rules and a calibrated model rate the severity and keep a short list of likely levels.
            </li>
            <li>
              An agent tests its ideas with read-only tools and finds the closest past incidents and
              the runbook they used.
            </li>
            <li>The report cites its evidence for every claim.</li>
            <li>
              The messages wait as drafts until a person approves them. Then the incident is
              published and joins ARIA&apos;s memory.
            </li>
            <li>The test results, caveats included.</li>
          </ol>
        </details>
      </figcaption>
    </figure>
  );
}
