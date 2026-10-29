---
slug: zookeeper-quorum-loss
title: ZooKeeper quorum connection loss
systems: [zookeeper]
failure_modes: [quorum_connection_loss]
risk: high
---

## When to use

`Connection broken for id`, `Cannot open channel to`, `Interrupted while waiting for message`
or `Send worker leaving thread` between ensemble peers.

## Diagnose

1. Ask each server for its mode and zxid (`srvr` or `mntr` four-letter commands, if allowed by `4lw.commands.whitelist`).
2. Check network reachability between peers on the quorum and election ports (2888 and 3888 by default).
3. Check for long JVM garbage-collection pauses and slow transaction-log disks on the peers that drop out.
4. Confirm whether a majority of servers is still serving; without one, clients cannot write.

## Mitigate

1. Restore connectivity between peers first; most quorum losses are network partitions. [risk: medium]
2. Restart failed peers one at a time and wait for each to rejoin; never restart a majority at once. [risk: high]

## Verify

1. Exactly one leader, every other peer a follower, and zxids converging.
2. Client sessions reconnect and dependent services recover.

## Escalate

Page the platform team immediately if the ensemble has lost its majority.
