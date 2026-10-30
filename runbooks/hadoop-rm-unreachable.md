---
slug: hadoop-rm-unreachable
title: MapReduce tasks cannot reach the ResourceManager
systems: [hadoop]
failure_modes: [resourcemanager_unreachable]
risk: medium
---

## When to use

`ERROR IN CONTACTING RM`, `Address change detected` or `NoRouteToHostException` from task
attempts.

## Diagnose

1. Check that the ResourceManager is up; with high availability, check which instance is active (`yarn rmadmin -getServiceState <id>`).
2. Check host-name resolution and routes from the failing nodes to the ResourceManager address.
3. Check whether an address change came from a failover or a configuration change.

## Mitigate

1. Fail over to the standby ResourceManager if the active one is unhealthy. [risk: medium]
2. Fix DNS or host entries so every node resolves the current ResourceManager address. [risk: medium]

## Verify

1. New applications are accepted and tasks report progress without contact errors.

## Escalate

Escalate to the Hadoop platform team if both ResourceManagers are unreachable.
