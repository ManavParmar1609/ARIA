---
slug: lustre-mount-failure
title: Lustre mount failures on I/O nodes
systems: [bgl]
failure_modes: [lustre_mount_failure]
risk: medium
---

## When to use

`Lustre mount FAILED` on I/O nodes, usually followed by job failures that need the file system.

## Diagnose

1. Check metadata and object storage server health (`lfs check servers`, `lctl ping` to the servers).
2. Check the LNET path between the I/O nodes and storage: link state, routes and recent network events.
3. Check whether every I/O node fails or only one group, which separates a storage outage from a network partition.

## Mitigate

1. Hold the scheduler queue for jobs that need the file system, so they do not fail on start. [risk: medium]
2. Restore the storage servers or network path, then remount on the I/O nodes. [risk: medium]
3. Release the queue once mounts succeed.

## Verify

1. Every I/O node shows the file system mounted and a test read/write succeeds.

## Escalate

Page the storage team immediately if more than one storage server is unreachable.
