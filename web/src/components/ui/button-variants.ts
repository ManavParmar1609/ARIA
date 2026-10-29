import { cva } from "class-variance-authority";

// Kept apart from <Button> so a component can use the styles without pulling in tailwind-merge.
// Auros (DESIGN.md): the aurora gradient is the one primary action in a view; everything else is
// a quiet fill or text. No shadows, 6 px radius.
export const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-[background-color,color,filter,opacity] duration-(--duration-quick) ease-(--ease-out) select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary:
          "bg-aurora tracking-[0.08em] text-sev-ink uppercase ring-1 ring-sev-ink/10 ring-inset hover:brightness-[1.04] active:brightness-95",
        secondary: "bg-foreground/8 text-heading hover:bg-foreground/14 active:bg-foreground/18",
        ghost:
          "text-muted-foreground hover:bg-foreground/6 hover:text-heading active:bg-foreground/10",
        danger: "bg-danger/12 text-danger hover:bg-danger/20 active:bg-danger/25",
        link: "h-auto px-0 text-foreground underline decoration-control underline-offset-4 hover:decoration-foreground",
      },
      size: {
        sm: "h-8 px-3 text-sm",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-sm",
        icon: "size-10",
        "icon-sm": "size-8",
      },
    },
    compoundVariants: [{ variant: "link", className: "h-auto px-0" }],
    defaultVariants: { variant: "secondary", size: "md" },
  },
);
