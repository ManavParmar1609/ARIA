import { Fragment, isValidElement, type ReactNode } from "react";

/*
 * Serialise a tree of plain SVG elements and pure function components (no hooks, no context) to
 * markup, so the illustration kit can also be served as static .svg files (src/app/art). The
 * illustrations are decorative, and drawing them as images keeps their thousands of nodes out of
 * the page's HTML, out of React's payload and out of hydration.
 */

// Attributes SVG spells in camel case; every other camel-cased prop becomes kebab case
// (strokeWidth -> stroke-width).
const CAMEL = new Set(["viewBox", "preserveAspectRatio"]);

const escapeText = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
const escapeAttr = (s: string) => escapeText(s).replace(/"/g, "&quot;");

function attrName(name: string): string {
  if (name === "className") return "class";
  if (CAMEL.has(name) || name.startsWith("aria-") || name.startsWith("data-")) return name;
  return name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
}

type Props = Record<string, unknown> & { children?: ReactNode };

export function renderSvg(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string") return escapeText(node);
  if (typeof node === "number" || typeof node === "bigint") return String(node);
  if (Array.isArray(node)) return node.map(renderSvg).join("");
  if (!isValidElement<Props>(node)) {
    throw new Error("renderSvg can only draw elements, text and arrays");
  }
  const { type, props } = node;
  if (type === Fragment) return renderSvg(props.children);
  if (typeof type === "function") {
    return renderSvg((type as (p: Props) => ReactNode)(props));
  }
  if (typeof type !== "string") throw new Error("renderSvg cannot draw this element type");
  let attrs = "";
  for (const [key, value] of Object.entries(props)) {
    if (key === "children" || value == null || value === false) continue;
    if (typeof value === "function" || typeof value === "object") continue;
    attrs += ` ${attrName(key)}="${escapeAttr(String(value))}"`;
  }
  const children = renderSvg(props.children);
  return children ? `<${type}${attrs}>${children}</${type}>` : `<${type}${attrs}/>`;
}
