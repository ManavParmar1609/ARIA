import { type VariantProps } from "class-variance-authority";
import { ChevronRightIcon } from "lucide-react";
import { Slot } from "radix-ui";
import { type ComponentProps } from "react";

import { cn } from "@/lib/utils";

import { arrowCircleVariants, buttonVariants } from "./button-variants";

export { buttonVariants };

export function Button({
  className,
  variant,
  size,
  asChild = false,
  type,
  ...props
}: ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      data-slot="button"
      type={asChild ? undefined : (type ?? "button")}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

/** The round arrow at the end of a call to action (decorative; the button's text names it). */
export function ArrowCircle({
  tone,
  size,
  className,
}: VariantProps<typeof arrowCircleVariants> & { className?: string }) {
  return (
    <span aria-hidden className={cn(arrowCircleVariants({ tone, size }), className)}>
      <ChevronRightIcon strokeWidth={2.25} className="size-4" />
    </span>
  );
}
