import { cva } from "class-variance-authority";

// Kept apart from <Button> so a component can use the styles without pulling in tailwind-merge.
// Greenhouse style (DESIGN.md): soft 10 to 14 px corners and no shadows. The main action in a view
// is forest ink with cream text; a cream button with a hairline sits beside it, and quiet actions
// are a faint ink tint or a ghost.
export const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center gap-2 font-medium whitespace-nowrap transition-[background-color,color,opacity,scale] duration-(--duration-quick) ease-(--ease-out) select-none active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:bg-primary-hover",
        raised: "bg-raised text-heading ring-1 ring-rule ring-inset hover:bg-sunken",
        secondary: "bg-foreground/6 text-heading hover:bg-foreground/10 active:bg-foreground/14",
        // Dot bloom: the hover fill grows out of a dot at the centre, quickly, and shrinks back
        // faster. A circle twice the button's width covers it from there; overflow clips it to the
        // button's corners. Keyboard focus fills it at once: keys should never wait on motion.
        ghost:
          "relative isolate overflow-hidden text-muted-foreground before:pointer-events-none before:absolute before:top-1/2 before:left-1/2 before:-z-10 before:aspect-square before:w-[200%] before:-translate-1/2 before:scale-[0.15] before:rounded-full before:bg-foreground/6 before:opacity-0 before:transition-[scale,opacity,background-color] before:duration-[120ms] before:ease-(--ease-out) hover:text-heading hover:before:scale-100 hover:before:opacity-100 hover:before:duration-(--duration-quick) focus-visible:before:scale-100 focus-visible:before:opacity-100 focus-visible:before:transition-none active:before:bg-foreground/10",
        danger: "bg-danger/12 text-danger hover:bg-danger/18 active:bg-danger/24",
        link: "h-auto px-0 text-accent-ink underline decoration-accent-ink/35 underline-offset-4 hover:decoration-accent-ink",
      },
      size: {
        sm: "h-8 rounded-sm px-3 text-sm",
        md: "h-10 rounded-md px-4 text-sm",
        lg: "h-12 rounded-lg px-5 text-[1.0625rem]",
        icon: "size-10 rounded-md",
        "icon-sm": "size-8 rounded-sm",
      },
    },
    compoundVariants: [{ variant: "link", className: "h-auto px-0 active:scale-100" }],
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

/** The trailing arrow on a call to action; it nudges right on hover. */
export const arrowCircleVariants = cva(
  "shrink-0 transition-transform duration-(--duration-moderate) ease-(--ease-out) group-hover/button:translate-x-0.5",
  {
    variants: {
      tone: { light: "", powder: "", ink: "" },
      size: { sm: "size-4", md: "size-[1.1rem]", lg: "size-5" },
    },
    defaultVariants: { size: "md" },
  },
);
