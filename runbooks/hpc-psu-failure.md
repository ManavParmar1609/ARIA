---
slug: hpc-psu-failure
title: Power-supply failures on HPC nodes
systems: [hpc]
failure_modes: [psu_failure]
risk: medium
---

## When to use

`psu failure` messages, often with ambient temperature readings.

## Diagnose

1. Check whether the enclosure still has redundant power (N+1) or is running on its last supply.
2. Check ambient temperature and cooling in the affected racks.
3. Check whether failures cluster in one rack or power feed.

## Mitigate

1. If redundancy is lost, drain the affected nodes before they lose power. [risk: medium]
2. Replace the failed power supplies. [risk: medium]
3. Fix cooling if ambient temperature is high.

## Verify

1. Every supply reports healthy and redundancy is restored.

## Escalate

Page facilities and hardware support if several supplies fail in one rack or power feed.
