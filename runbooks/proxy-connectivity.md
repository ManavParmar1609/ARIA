---
slug: proxy-connectivity
title: Clients cannot connect through the proxy
systems: [proxifier]
failure_modes: [proxy_connectivity]
risk: low
---

## When to use

`Could not connect to proxy ... connection attempt failed` from Proxifier clients.

## Diagnose

1. Check that the proxy server is reachable on its port from an affected client.
2. Check proxy authentication and whether credentials changed.
3. Check DNS resolution of the proxy host name.

## Mitigate

1. Restore the proxy service or fail clients over to a secondary proxy. [risk: medium]

## Verify

1. Clients connect through the proxy and the error rate returns to zero.

## Escalate

Escalate to the network team if the proxy is down for many clients.
