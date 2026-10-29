---
slug: bgl-tree-network
title: Tree-network packet errors
systems: [bgl]
failure_modes: [tree_network_errors]
risk: medium
---

## When to use

`error receiving packet on tree network` from KERNEL.

## Diagnose

1. Map the affected nodes to midplanes and link cards; errors that cluster on one link card point to cabling or the card.
2. Correlate with link-card and LINKCARD events in the same window.

## Mitigate

1. Stop scheduling new jobs on the affected midplane. [risk: medium]
2. Schedule cable reseating or link-card replacement with hardware support. [risk: high]

## Verify

1. A collective-communication test job runs without packet errors.

## Escalate

Escalate to hardware support when errors persist after the midplane is idle.
