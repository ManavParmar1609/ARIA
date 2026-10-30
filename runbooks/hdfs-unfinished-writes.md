---
slug: hdfs-unfinished-writes
title: HDFS block writes that stop partway
systems: [hdfs]
failure_modes: [unfinished_work]
risk: low
---

## When to use

ARIA reports HDFS blocks that never finished every step: a block received by its datanodes but
not confirmed by all of them (`Received block`, `PacketResponder ... terminating` or
`addStoredBlock` missing), often with no error logged. Each such block is short of a replica
until HDFS copies it again.

## Diagnose

1. Open the blocks ARIA flagged and note which step is missing and which datanodes they share; failures that cluster on one or two datanodes usually mean a failing node or disk.
2. Look in those datanodes' logs for `writeBlock ... received exception`, `Exception in receiveBlock` or `Receiving empty packet` around the same time.
3. Check for dead or stale datanodes (`hdfs dfsadmin -report`) and for under-replicated blocks (`hdfs fsck / -blocks -locations | grep -i under`).
4. Check the network between the affected datanodes: write pipelines fail when a transfer between them stalls.

## Mitigate

1. Let HDFS re-replicate: confirm the NameNode is scheduling the copies (`ask ... to replicate` lines) and that the under-replicated count falls.
2. Restart the datanode process on a node whose write pipelines keep failing.
3. Decommission a datanode with a failing disk so its blocks move elsewhere. [risk: medium]

## Verify

1. `hdfs fsck /` reports no missing or under-replicated blocks, and a new ARIA run finds no unfinished blocks.

## Escalate

Escalate immediately if any block is missing every replica (`fsck` reports missing or corrupt
blocks), or if unfinished writes spread across many datanodes at once.
