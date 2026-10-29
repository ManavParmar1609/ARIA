---
slug: hdfs-lease-renewal
title: HDFS lease renewal failures
systems: [hadoop]
failure_modes: [hdfs_lease_renewal]
risk: low
---

## When to use

`Failed to renew lease` from HDFS clients (task attempts holding files open).

## Diagnose

1. Check NameNode health and RPC latency (`hdfs dfsadmin -report`, NameNode RPC queue metrics).
2. Check for long garbage-collection pauses on the clients that fail to renew.
3. Check network connectivity from the failing nodes to the NameNode.

## Mitigate

1. Reduce load on the NameNode (pause heavy batch jobs) if RPC queues are saturated. [risk: medium]
2. Fix connectivity or client GC pressure on the affected nodes.

## Verify

1. Lease renewal errors stop and affected tasks finish writing their output.

## Escalate

Escalate to the platform team if the NameNode is unresponsive.
