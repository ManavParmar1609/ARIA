import { cva } from "class-variance-authority";

// Kept apart from <Button> so a component can use the styles without pulling in tailwind-merge.
export const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow] duration-(--duration-quick) ease-(--ease-out) select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:bg-primary/88 active:bg-primary/80",
        secondary:
          "border border-control bg-transparent text-foreground hover:bg-sunken active:bg-sunken/70",
        ghost: "text-foreground hover:bg-sunken active:bg-sunken/70",
        danger:
          "border border-danger/70 bg-transparent text-danger hover:bg-danger/10 active:bg-danger/15",
        link: "h-auto px-0 text-foreground underline decoration-control underline-offset-4 hover:decoration-foreground",
      },
      size: {
        sm: "h-8 px-3 text-sm",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "size-10",
        "icon-sm": "size-8",
      },
    },
    compoundVariants: [{ variant: "link", className: "h-auto px-0" }],
    defaultVariants: { variant: "secondary", size: "md" },
  },
);
