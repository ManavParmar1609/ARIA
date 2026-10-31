/**
 * What a person reads when ARIA's server does not answer: on the free demo it sleeps when idle
 * and restarts now and then, so this is usually a short wait, not a fault to go and fix.
 */
export const UNREACHABLE =
  "ARIA's server isn't answering. It may be starting up or restarting: wait a moment and try again.";
