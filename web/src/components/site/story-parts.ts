// The parts of the console's How ARIA works page, in reading order. Each part is a page of its own
// so none is a long scroll; the home page links straight to the one it mentions.
export const STORY_PARTS = [
  { href: "/console/how-it-works", label: "What it does" },
  { href: "/console/how-it-works/example", label: "An example" },
  { href: "/console/how-it-works/steps", label: "The four steps" },
  { href: "/console/how-it-works/results", label: "Test results" },
  { href: "/console/how-it-works/questions", label: "Questions" },
] as const;
