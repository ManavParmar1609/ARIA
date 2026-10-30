---
slug: bgl-memory-interrupts
title: Data TLB and data storage interrupts on compute nodes
systems: [bgl]
failure_modes: [memory_interrupts]
risk: low
---

## When to use

`data TLB error interrupt` or `data storage interrupt` messages from KERNEL.

## Diagnose

1. Check whether the interrupts follow one application across many nodes (likely an application bug) or one node across many jobs (likely hardware).
2. Correlate with ECC, bit-sparing or memory-error events on the same nodes.
3. Identify the job and its owner from the scheduler for the affected window.

## Mitigate

1. If one application is the source, notify the job owner with the failing addresses and stop resubmissions until it is fixed.
2. If one node is the source, drain it and run memory diagnostics. [risk: medium]

## Verify

1. The interrupt rate drops to zero once the job is stopped or the node is drained.

## Escalate

Escalate to hardware support if diagnostics confirm a memory fault.
