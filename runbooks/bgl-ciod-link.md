---
slug: bgl-ciod-link
title: CIOD control-stream link failures
systems: [bgl]
failure_modes: [ciod_link_failure]
risk: medium
---

## When to use

`ciod: ... link has been severed`, `failed to read message prefix`, `Connection reset by peer`
or timeouts from the control and I/O daemon (ciod) on I/O nodes.

## Diagnose

1. Check whether the errors come from one I/O node (and its processor set) or many.
2. Check functional-network health between the I/O nodes and the service and front-end nodes.
3. Check whether the jobs on the affected processor sets were killed or only delayed.

## Mitigate

1. Restart the I/O node that carries the failing ciod. [risk: medium]
2. Requeue jobs whose processor sets lost their control stream.

## Verify

1. New jobs on the affected processor sets start and finish without ciod errors.

## Escalate

Escalate to the system administrators if many I/O nodes fail at once; that points to the
functional network or the service node.
