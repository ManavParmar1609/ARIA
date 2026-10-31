/**
 * Text in which `backticks` mark code, as runbooks write commands and settings: each pair becomes
 * a code span. An unpaired backtick stays as typed, so a stray one never turns the rest into code.
 */
export function CodeText({ children }: { children: string }) {
  const parts = children.split("`");
  if (parts.length % 2 === 0) return <>{children}</>;
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <code key={i} className="rounded-xs bg-sunken px-1 py-0.5 text-[0.85em]">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}
