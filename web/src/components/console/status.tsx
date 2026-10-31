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
    // The main action's forest pill, like the sidebar's count: the one state that waits on a
    // person, set apart from the plain green text of a published run.
    className: "rounded-full border-primary bg-primary px-2 text-primary-foreground",
    icon: UserRoundCheckIcon,
  },
  published: { label: "Published", className: "text-ok", icon: CircleCheckIcon },
  rejected: { label: "Discarded", className: "text-muted-foreground", icon: CircleXIcon },
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
