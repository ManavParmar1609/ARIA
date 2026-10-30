---
slug: generic-triage
title: First response for an unclassified incident
systems: ["*"]
failure_modes: ["*"]
risk: low
---

## When to use

No specific runbook matches the failure, or the evidence points in several directions.

## Diagnose

1. Establish scope: which services, nodes and customers are affected, and since when.
2. Compare the error templates with the last known-good window to find what is new.
3. Check recent changes (deploys, configuration, infrastructure) in the window before onset.
4. Check dependencies the failing component calls (databases, DNS, storage, network).

## Mitigate

1. If a recent change lines up with the onset, roll it back. [risk: medium]
2. Shed or reroute load away from failing nodes if the service supports it. [risk: medium]
3. Keep a running timeline in the incident channel and post updates at a fixed cadence.

## Verify

1. Error rate and latency return to the pre-incident baseline for at least 15 minutes.
2. No new error templates appear after mitigation.

## Escalate

Page the owning team when customer impact is confirmed or the scope keeps growing.
