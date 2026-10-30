---
slug: dns-resolution
title: Name resolution failures
systems: [thunderbird]
failure_modes: [dns_resolution]
risk: low
---

## When to use

`failed to resolve data source name` or `unqualified host name` errors.

## Diagnose

1. Check the resolvers configured on the affected nodes (`/etc/resolv.conf`) and whether they answer.
2. Check the DNS server's health and logs.
3. Check for recent changes to host names or monitoring data-source definitions.

## Mitigate

1. Restore the DNS service or point the nodes to a healthy resolver. [risk: medium]
2. Fix data-source definitions that use unqualified host names.

## Verify

1. Lookups succeed from the affected nodes and the errors stop.

## Escalate

Escalate to the network team if resolution fails cluster-wide.
