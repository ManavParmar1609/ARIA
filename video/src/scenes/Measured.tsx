import { useCurrentFrame } from "remotion";

import { Heading, Stage } from "../components";
import { measured, publicAttacks, realLogs } from "../data";
import { enter } from "../motion";
import { color, serif, size } from "../theme";

const Row = ({
  start,
  figure,
  label,
  note,
}: {
  start: number;
  figure: string;
  label: string;
  note: string;
}) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "360px 1fr",
        gap: 40,
        alignItems: "baseline",
        ...enter(frame, start),
      }}
    >
      <span
        style={{
          ...serif,
          fontSize: 96,
          letterSpacing: "-0.02em",
          lineHeight: 1,
          fontVariantNumeric: "lining-nums tabular-nums",
          color: color.heading,
        }}
      >
        {figure}
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span style={{ fontSize: 40, color: color.heading }}>{label}</span>
        <span style={{ fontSize: 30, color: color.muted }}>{note}</span>
      </div>
    </div>
  );
};

/** Four results from `make eval`, with their caveat on screen the whole time. */
export const Measured = () => {
  const frame = useCurrentFrame();
  return (
    <Stage>
      <Heading>Measured, caveats included.</Heading>
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        <Row
          start={20}
          figure={measured.accuracy}
          label={`severity accuracy on ${measured.windows} held-out windows`}
          note={`A text classifier on the same lines: ${measured.tfidf}. Rules alone: ${measured.rules}.`}
        />
        <Row
          start={80}
          figure={measured.cited}
          label={`of ${measured.runs} end-to-end reports cite evidence for every claim`}
          note="Claims that cite nothing are repaired or replaced before anyone sees them."
        />
        <Row
          start={140}
          figure={realLogs.precision}
          label="of its flags on real HDFS logs were real failures"
          note={`By the experts' labels. It caught ${realLogs.recall} of the failures it could judge, ${realLogs.recallAll} of all.`}
        />
        <Row
          start={200}
          figure={publicAttacks.caught}
          label={`of ${publicAttacks.attacks} public prompt-injection attacks caught`}
          note={`From ${publicAttacks.benchmarks} benchmarks it was never tuned on. Fencing and approval do not rely on it.`}
        />
      </div>
      <p
        style={{
          margin: 0,
          marginTop: "auto",
          fontSize: 30,
          color: color.faint,
          ...enter(frame, 10),
        }}
      >
        The first two use semi-synthetic incidents built from real Loghub lines, so they are not
        accuracy on production incidents; the last two are one real log and attacks written by
        others. Method and every number: docs/evaluation.md ({measured.commit}).
      </p>
    </Stage>
  );
};
