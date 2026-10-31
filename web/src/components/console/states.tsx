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
  art,
  title,
  children,
  action,
  className,
  heading: Title = "p",
}: {
  icon?: LucideIcon;
  /** A small illustration, shown beside the words on wider screens (it replaces the icon). */
  art?: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
  /** "h1" where the state is the whole page, such as a link to something that is not there. */
  heading?: "p" | "h1";
}) {
  return (
    <div
      className={cn(
        "grid items-center gap-6 rounded-lg bg-raised px-6 py-8 sm:px-8",
        art && "sm:grid-cols-[minmax(0,1fr)_11rem] md:grid-cols-[minmax(0,1fr)_13rem]",
        className,
      )}
    >
      <div className="grid justify-items-start gap-3">
        {Icon && !art ? (
          <Icon aria-hidden className="size-5 text-foreground" strokeWidth={1.5} />
        ) : null}
        <Title className="text-xl font-medium text-heading">{title}</Title>
        {children ? <div className="max-w-prose text-muted-foreground">{children}</div> : null}
        {action}
      </div>
      {art ? <div className="hidden w-full sm:block">{art}</div> : null}
    </div>
  );
}

/** What went wrong and what to do about it, never an apology. The title names what failed. */
export function ErrorState({
  error,
  title,
  onRetry,
  action,
  className,
}: {
  error: unknown;
  title: string;
  onRetry?: () => void;
  /** Another way forward beside "Try again", such as a link back. */
  action?: ReactNode;
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
      <p className="max-w-full text-sm wrap-anywhere text-muted-foreground">{detail}</p>
      {onRetry || action ? (
        <div className="flex flex-wrap gap-2">
          {onRetry ? (
            <Button size="sm" onClick={onRetry}>
              Try again
            </Button>
          ) : null}
          {action}
        </div>
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
          {eyebrow ? (
            <p className="eyebrow inline-flex items-center gap-2 text-muted-foreground">
              <span
                aria-hidden
                className="block size-2 rounded-full bg-primary ring-2 ring-primary/20"
              />
              {eyebrow}
            </p>
          ) : null}
          <h1 className="text-[2.25rem] leading-none tracking-heading sm:text-4xl">{title}</h1>
          {description ? (
            <p className="max-w-prose text-lg text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </header>
  );
}
