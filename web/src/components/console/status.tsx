import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleXIcon,
  LoaderCircleIcon,
  OctagonAlertIcon,
  UserRoundCheckIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

const STATUS: Record<string, { label: string; className: string; icon: typeof CircleCheckIcon }> = {
  queued: { label: "Queued", className: "text-muted-foreground", icon: CircleDashedIcon },
  running: { label: "Running", className: "text-foreground", icon: LoaderCircleIcon },
  awaiting_review: {
    label: "Needs review",
    // ink, like the sidebar's count: the state that needs a person must not read as done (green)
    className: "bg-foreground text-background border-foreground",
    icon: UserRoundCheckIcon,
  },
  published: { label: "Published", className: "text-ok", icon: CircleCheckIcon },
  rejected: { label: "Rejected", className: "text-muted-foreground", icon: CircleXIcon },
  failed: { label: "Failed", className: "text-danger", icon: OctagonAlertIcon },
};

export const STATUS_LABEL = Object.fromEntries(
  Object.entries(STATUS).map(([k, v]) => [k, v.label]),
);

export function RunStatus({ status, className }: { status: string; className?: string }) {
  const spec = STATUS[status] ?? { label: status, className: "", icon: CircleDashedIcon };
  const Icon = spec.icon;
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-xs border border-transparent px-1.5 text-xs font-medium whitespace-nowrap",
        spec.className,
        className,
      )}
    >
      <Icon
        aria-hidden
        className={cn(
          "size-3.5",
          status === "running" && "animate-spin motion-reduce:animate-none",
        )}
      />
      {spec.label}
    </span>
  );
}

const DECIDED: Record<string, string> = {
  rules: "Rules",
  model: "Model",
  llm: "LLM, within the model's set",
  fallback: "Unsure, flagged for review",
  human: "Reviewer",
};

export function decidedByLabel(decidedBy: string | null | undefined): string {
  return decidedBy ? (DECIDED[decidedBy] ?? decidedBy) : "";
}
