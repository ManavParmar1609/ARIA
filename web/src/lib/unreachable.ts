/**
 * What a person reads when ARIA's server does not answer: on the free demo it sleeps when idle
 * and restarts now and then, so this is usually a short wait, not a fault to go and fix.
 */
// Said in the past tense: the message stays beside the action it answered, and the server may be
// back by the time it is read (SL-m4).
export const UNREACHABLE =
  "ARIA's server wasn't answering. It may have been starting up or restarting: wait a moment and try again.";
