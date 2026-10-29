---
slug: ssh-bruteforce
title: SSH brute-force or credential-guessing attempts
systems: [openssh, linux]
failure_modes: [bruteforce, auth_failures]
risk: low
---

## When to use

Bursts of `Failed password`, `Invalid user`, `authentication failure` or
`POSSIBLE BREAK-IN ATTEMPT` across one or more hosts.

## Diagnose

1. Count attempts per source address and per targeted account; note how many hosts are targeted.
2. Check for any successful login (`Accepted password` or `Accepted publickey`) from the same sources after the failures.
3. Check whether privileged accounts (root, service accounts) were targeted.

## Mitigate

1. Block the offending sources at the firewall or with fail2ban.
2. Disable password authentication and root login over SSH where keys are available (`PasswordAuthentication no`, `PermitRootLogin no`). [risk: medium]
3. If any login succeeded from an attacking source, treat the host as compromised: isolate it and rotate the affected credentials. [risk: high]

## Verify

1. Failed-login rate returns to baseline and blocked sources stop appearing.

## Escalate

Page security at once if any attempt succeeded or privileged accounts were targeted across many
hosts.
