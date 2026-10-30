---
slug: openstack-image-cache
title: Nova image cache reports unknown base files
systems: [openstack]
failure_modes: [image_cache_missing]
risk: low
---

## When to use

`Unknown base file: /var/lib/nova/instances/_base/...` from the Nova image cache manager.

## Diagnose

1. Confirm the messages come from the periodic image cache manager, which reports base images no instance uses.
2. Check free disk space under the instances directory on the affected compute hosts.

## Mitigate

1. No action is needed if disk space is healthy; the messages are informational.
2. If disk is short, let the cache manager remove unused base images (`remove_unused_base_images`). [risk: medium]

## Verify

1. Disk usage on the compute hosts is stable.

## Escalate

None, unless instances fail to boot because base images are missing.
