---
slug: hdfs-block-serve
title: DataNodes failing to serve blocks
systems: [hdfs]
failure_modes: [block_serve_exceptions]
risk: low
---

## When to use

`Got exception while serving blk_...` from DataNodes.

## Diagnose

1. Check whether the errors concentrate on one DataNode (often a failing disk) or spread across many (often clients disconnecting or the network).
2. Check disk health and I/O errors on the DataNodes with the most errors.
3. Check for missing or corrupt blocks (`hdfs fsck / -list-corruptfileblocks`).

## Mitigate

1. Decommission a DataNode whose disk is failing so its blocks re-replicate. [risk: medium]
2. If clients are disconnecting, look for the job or network change that causes it.

## Verify

1. No missing or under-replicated blocks remain and the error rate is back to baseline.

## Escalate

Escalate immediately if `fsck` reports corrupt or missing blocks.
