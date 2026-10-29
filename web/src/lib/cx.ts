/**
 * Joins class names without resolving Tailwind conflicts. For components whose callers never
 * override a base utility, so the landing page ships without tailwind-merge and its start-up cost;
 * everything else uses `cn`.
 */
export { clsx as cx } from "clsx";
