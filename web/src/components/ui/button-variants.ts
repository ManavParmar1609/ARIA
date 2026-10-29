import { cva } from "class-variance-authority";

// Kept apart from <Button> so a component can use the styles without pulling in tailwind-merge.
// Cream-paper style (DESIGN.md): crisp 6 px corners, no shadows. A button stands out from the
// surface it sits on: grass for the one main action in a view, white on cream or grass, a quiet
// ink tint otherwise. The four pops are for the story cards on the landing page, one per card.
export const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-[background-color,color,opacity,scale] duration-(--duration-quick) ease-(--ease-out) select-none active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary: "bg-grass text-pop-ink hover:bg-grass-deep",
        raised: "bg-raised text-heading hover:bg-raised/85",
        secondary: "bg-foreground/7 text-heading hover:bg-foreground/12 active:bg-foreground/16",
        ghost:
          "text-muted-foreground hover:bg-foreground/6 hover:text-heading active:bg-foreground/10",
        danger: "bg-danger/12 text-danger hover:bg-danger/20 active:bg-danger/25",
        link: "h-auto px-0 text-foreground underline decoration-control underline-offset-4 hover:decoration-foreground",
        coral: "bg-coral text-pop-ink hover:bg-coral/85",
        sunshine: "bg-sunshine text-pop-ink hover:bg-sunshine/85",
        sky: "bg-sky text-pop-ink hover:bg-sky/85",
        lilac: "bg-lilac text-pop-ink hover:bg-lilac/80",
      },
      size: {
        sm: "h-9 px-3 text-sm",
        md: "h-11 px-4 text-sm",
        lg: "h-14 px-5 text-lg",
        icon: "size-10",
        "icon-sm": "size-9",
      },
    },
    compoundVariants: [{ variant: "link", className: "h-auto px-0 active:scale-100" }],
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

/** The round arrow that ends a call to action: grass on white buttons, white on coloured ones. */
export const arrowCircleVariants = cva(
  "grid shrink-0 place-items-center rounded-full text-pop-ink transition-transform duration-(--duration-moderate) ease-(--ease-out) group-hover/button:translate-x-0.5",
  {
    variants: {
      tone: { grass: "bg-grass", white: "bg-white", ink: "bg-foreground text-background" },
      size: { sm: "size-7", md: "size-8", lg: "size-10" },
    },
    defaultVariants: { tone: "grass", size: "lg" },
  },
);
