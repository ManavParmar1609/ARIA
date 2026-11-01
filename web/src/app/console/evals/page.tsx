import type { Metadata } from "next";

import { Evals } from "@/components/console/evals";
import { evaluation, generalisation, realData, realLogs, tuningRecord } from "@/lib/site-data";

export const metadata: Metadata = { title: "Test results" };

export default function EvalsPage() {
  return (
    <Evals
      data={evaluation()}
      real={realLogs()}
      more={realData()}
      unseen={generalisation()}
      tuning={tuningRecord()}
    />
  );
}
