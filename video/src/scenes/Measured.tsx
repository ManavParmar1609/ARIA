import { useCurrentFrame } from "remotion";

import { Heading, Stage } from "../components";
import { measured, realLogs } from "../data";
import { enter } from "../motion";
import { color, size } from "../theme";

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
          fontSize: 88,
          fontWeight: 500,
          letterSpacing: "-0.046em",
          lineHeight: 1,
          fontVariantNumeric: "tabular-nums",
          color: color.stat,
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
          figure={measured.quarantined}
          label={`of ${measured.attacks} prompt-injection attempts quarantined`}
          note={`${measured.falsePositives} of ${measured.benign} benign look-alikes. An upper bound: the detector was tuned on this corpus.`}
        />
        <Row
          start={200}
          figure={realLogs.precision}
          label="of its flags on real HDFS logs were real failures"
          note={`By the experts' labels. It caught ${realLogs.recall} of the failures it could judge, ${realLogs.recallAll} of all.`}
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
        The first three use semi-synthetic incidents built from real Loghub lines, so they are not
        accuracy on production incidents; the last is one real log from one system. Method and every
        number: docs/evaluation.md ({measured.commit}).
      </p>
    </Stage>
  );
};
