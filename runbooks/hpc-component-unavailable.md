---
slug: hpc-component-unavailable
title: Hardware components unavailable on HPC nodes
systems: [hpc]
failure_modes: [component_unavailable]
risk: medium
---

## When to use

`Component State Change: Component ... is in the unavailable state` messages.

## Diagnose

1. List the hardware IDs that changed state and the nodes they belong to.
2. Check the hardware controller or management interface for the reason.

## Mitigate

1. Drain the nodes whose components are unavailable. [risk: medium]
2. Replace or reset the failed components with hardware support. [risk: medium]

## Verify

1. The components report an available state and the nodes pass health checks.

## Escalate

Escalate to hardware support for any component that does not recover after a reset.
