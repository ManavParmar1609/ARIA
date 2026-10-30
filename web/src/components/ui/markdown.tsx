import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/**
 * Markdown from ARIA (reports, runbooks). Raw HTML is never rendered, so text that came from
 * logs cannot inject markup.
 */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div
      className={cn(
        "grid gap-3 text-sm leading-relaxed [&_code]:rounded-xs [&_code]:bg-sunken [&_code]:px-1 [&_h1]:text-lg [&_h1]:font-medium [&_h2]:mt-2 [&_h2]:text-base [&_h2]:font-medium [&_h3]:font-medium [&_li]:ml-5 [&_ol]:list-decimal [&_table]:w-full [&_table]:text-xs [&_td]:border-b [&_td]:border-rule [&_td]:px-2 [&_td]:py-1 [&_th]:border-b [&_th]:border-rule [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_ul]:list-disc [&_ul.contains-task-list]:list-none",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          // A GFM task box renders as a disabled, unlabelled checkbox. Here it only marks a to-do,
          // so draw the mark and keep it out of the accessibility tree.
          input: ({ checked }) => (
            <span
              aria-hidden
              className={cn(
                "mr-1.5 inline-block size-3 rounded-[3px] border border-control align-[-1px]",
                checked && "bg-foreground",
              )}
            />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
