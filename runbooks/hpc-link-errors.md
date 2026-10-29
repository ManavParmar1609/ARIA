---
slug: hpc-link-errors
title: Interconnect link errors on HPC nodes
systems: [hpc]
failure_modes: [interconnect_link_errors]
risk: low
---

## When to use

`Linkerror event interval expired` or `link errors remain current` messages.

## Diagnose

1. Map the errors to switch ports and cables; errors confined to one port point to that cable or transceiver.
2. Check the port error counters on the switch side.

## Mitigate

1. Drain the affected nodes if job performance suffers. [risk: medium]
2. Reseat or replace the cable or transceiver during a maintenance window. [risk: medium]

## Verify

1. Link error counters stop increasing after the fix.

## Escalate

Escalate to the network or hardware team if errors span many ports on one switch.
