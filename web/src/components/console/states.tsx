import { CircleAlertIcon, type LucideIcon } from "lucide-react";
import { type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/** Placeholder rows while data loads; announced once to screen readers. */
export function LoadingRows({
  rows = 5,
  label = "Loading",
  className,
}: {
  rows?: number;
  label?: string;
  className?: string;
}) {
  return (
    <div role="status" aria-live="polite" className={cn("grid gap-2", className)}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid justify-items-start gap-3 rounded-lg bg-sunken px-6 py-10 sm:px-8",
        className,
      )}
    >
      {Icon ? <Icon aria-hidden className="size-5 text-primary" strokeWidth={1.5} /> : null}
      <p className="text-lg font-medium text-heading">{title}</p>
      {children ? (
        <div className="max-w-prose text-sm text-muted-foreground">{children}</div>
      ) : null}
      {action}
    </div>
  );
}

/** What went wrong and what to do about it, never an apology. */
export function ErrorState({
  error,
  title = "This could not be loaded",
  onRetry,
  className,
}: {
  error: unknown;
  title?: string;
  onRetry?: () => void;
  className?: string;
}) {
  const detail =
    error instanceof ApiError
      ? error.detail
      : error instanceof Error
        ? error.message
        : "Unexpected error.";
  return (
    <div
      role="alert"
      className={cn("grid justify-items-start gap-3 rounded-lg bg-danger/10 px-6 py-6", className)}
    >
      <p className="flex items-center gap-2 font-medium text-danger">
        <CircleAlertIcon aria-hidden className="size-4" />
        {title}
      </p>
      <p className="text-sm text-muted-foreground">{detail}</p>
      {onRetry ? (
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
}: {
  /** The section of the console the page belongs to, as the navigation names it. */
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="grid gap-4 pb-2">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid min-w-0 gap-3">
          {eyebrow ? <p className="eyebrow text-muted-foreground">{eyebrow}</p> : null}
          <h1 className="text-3xl leading-none tracking-heading sm:text-4xl sm:tracking-display">
            {title}
          </h1>
          {description ? <p className="max-w-3xl text-muted-foreground">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </header>
  );
}
