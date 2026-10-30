---
slug: apache-mod-jk
title: Apache mod_jk workers in error state
systems: [apache]
failure_modes: [mod_jk_worker_error]
risk: low
---

## When to use

`mod_jk child workerEnv in error state` or `Can't find child ... in scoreboard`.

## Diagnose

1. Check the Tomcat back ends behind the mod_jk workers: process up, AJP connector listening, thread pool not exhausted.
2. Check `workers.properties` for back ends that were removed or renamed.
3. Check whether every Apache server reports errors or only some.

## Mitigate

1. Restart unhealthy Tomcat back ends one at a time. [risk: medium]
2. Gracefully reload Apache if its worker state is stale (`apachectl graceful`). [risk: low]

## Verify

1. Requests through mod_jk succeed and the error messages stop.

## Escalate

Escalate to the application team if back ends keep failing after restarts.
