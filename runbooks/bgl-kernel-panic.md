---
slug: bgl-kernel-panic
title: Kernel panics on BlueGene/L compute nodes
systems: [bgl]
failure_modes: [kernel_panic]
risk: medium
---

## When to use

`rts panic! - stopping execution` or `rts: kernel terminated for reason ...` from KERNEL on one
or more compute nodes.

## Diagnose

1. List the affected node locations (rack, midplane, node card) and check whether they share a node card or midplane.
2. Look for machine-check, ECC or power events on the same nodes in the minutes before the panic.
3. Check which job was running on the partition and whether other jobs on the same hardware failed.
4. Check whether the same nodes panicked in previous incidents (repeat history).

## Mitigate

1. Drain the affected nodes in the scheduler so no new jobs land on them.
2. Free and reboot the affected block from the service node, then requeue the killed jobs. [risk: medium]
3. If panics repeat on the same node card, take it out of service for hardware diagnostics. [risk: medium]

## Verify

1. The block boots cleanly and a short diagnostic job completes.
2. No new panic messages from the affected locations for one full job cycle.

## Escalate

Escalate to hardware support when machine checks precede the panics or the same node card fails
twice in a week.
