import type { components } from "@/lib/api/schema";

import { modelKeyLabel } from "./api/model-key";

// Who answers a visitor's runs and questions (item B): their own key, else the site's own key
// while today's share lasts, else nobody, and the work runs offline. The same words appear on
// Settings and on New triage.

export type SharedModel = components["schemas"]["SharedModelOut"];

export type ModelAccess =
  | { kind: "own"; label: string }
  | { kind: "shared"; label: string; left: number | null }
  | { kind: "offline"; label: string; usedUp: boolean };

export function modelAccess(
  savedProvider: string | null,
  kinds: readonly string[],
  shared: SharedModel | null | undefined,
): ModelAccess {
  if (savedProvider && kinds.includes(savedProvider)) {
    return { kind: "own", label: `Your ${modelKeyLabel(savedProvider)} key` };
  }
  if (shared && shared.left !== 0) {
    const limited = shared.left != null;
    return {
      kind: "shared",
      label: limited ? "The site's key (shared, limited)" : "The site's key",
      left: shared.left ?? null,
    };
  }
  return { kind: "offline", label: "Offline", usedUp: shared?.left === 0 };
}

const OFFLINE = "the rules, the calibrated model and the grounded template";

/** One sentence: what answers, and what the visitor can do about it. */
export function accessSentence(access: ModelAccess, canBringKey: boolean): string {
  const bring = canBringKey ? " Add your own key in Settings to use a model." : "";
  switch (access.kind) {
    case "own":
      return `${access.label} answers your runs and questions.`;
    case "shared":
      return access.left == null
        ? "The site's key answers your runs and questions."
        : `The site's key (shared, limited) answers your runs and questions: ${access.left} left today.`;
    case "offline":
      return access.usedUp
        ? `Offline for today: your share of the site's key is used, so runs use ${OFFLINE}.${bring}`
        : `Offline: runs use ${OFFLINE}, and nothing leaves the server.${bring}`;
  }
}
