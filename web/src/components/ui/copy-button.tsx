"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Copies a block of text and says so for a moment, to a screen reader too. Where the browser
 * refuses the clipboard, nothing changes and the text stays there to select by hand.
 */
export function CopyButton({
  text,
  label,
  className,
}: {
  text: string;
  /** What is copied, after "Copy": "Copy the Alertmanager receiver". */
  label: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      return;
    }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2000);
  };
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className={cn("gap-1.5", className)}
        onClick={() => void copy()}
      >
        {copied ? <CheckIcon aria-hidden /> : <CopyIcon aria-hidden />}
        {copied ? "Copied" : "Copy"}
        {/* The name says what it copies; the visible word starts it, as WCAG 2.5.3 asks. */}
        <span className="sr-only"> {label}</span>
      </Button>
      <span role="status" className="sr-only">
        {copied ? "Copied" : ""}
      </span>
    </>
  );
}
