import { type ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const fieldClasses =
  "w-full min-w-0 rounded-md border border-control bg-sunken px-3 text-sm text-foreground placeholder:text-muted-foreground transition-[border-color,box-shadow] duration-(--duration-quick) outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-danger";

export function Input({ className, type = "text", ...props }: ComponentProps<"input">) {
  return (
    <input
      data-slot="input"
      type={type}
      className={cn(fieldClasses, "h-10", className)}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(fieldClasses, "min-h-24 py-2 leading-relaxed", className)}
      {...props}
    />
  );
}
