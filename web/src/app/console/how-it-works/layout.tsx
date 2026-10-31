import type { ReactNode } from "react";

import { PageHeader } from "@/components/console/states";
import { StoryNav, StoryPager } from "@/components/site/story-nav";

/** How ARIA works, in five short parts, each a page of its own: the home page's detail, kept here
 * so the home page stays short. It needs no API: everything comes from recorded files. */
export default function HowItWorksLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-10">
      <div className="grid gap-6">
        <PageHeader
          title="How ARIA works"
          description="A short tour in five parts. Read them in order, or jump to the one you need."
        />
        <StoryNav />
      </div>
      {children}
      <StoryPager />
    </div>
  );
}
