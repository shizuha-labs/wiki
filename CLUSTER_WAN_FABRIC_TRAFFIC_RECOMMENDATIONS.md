# Cluster WAN/Fabric Traffic Attribution Recommendations

This reusable planning template contains no installation inventory or incident data.
Keep node names, interface addresses, provider identifiers, traffic captures and
operator incident receipts in the installation's private operations knowledge base.

## Network inventory

Record the management, service, storage and fabric paths for each node. Identify
which routes carry public egress and which remain on private links. Derive the
inventory from the current deployment rather than copying another operator's
addresses or assuming that a logical service and its traffic share one host.

## Monitoring contract

Measure public and fabric traffic separately. Attribute traffic to the current
pod, workload and owning service using stable workload identity and timestamps.
Retain enough evidence to distinguish downloads, application requests, storage
replication and control-plane traffic. Compare host counters with workload-level
observations before assigning a culprit.

Treat unknown attribution as an instrumentation gap. Do not convert a process
name, a single address, or a stale owner mapping into a definitive billing claim.

## Incident investigation

1. Preserve the incident window and bounded counters before changing workloads.
2. Join current routes, endpoints, interface counters and workload ownership.
3. Verify whether the traffic crosses the public boundary or stays on the fabric.
4. Identify the originating producer and its configured cache or data path.
5. Review a scoped repair with its rollback and post-change measurements.

Capture packet headers only when needed and authorized; keep credentials and
application payloads out of shared logs. Never recycle unrelated workloads to
improve a monitoring graph.

## Installation-owned decisions

Document routing and cache policy, expected traffic classes, attribution limits,
alert ownership and approval boundaries in the private runbook. Apply changes
through the installation's normal source-reviewed delivery mechanism. Validate
both user-visible behavior and measured traffic after delivery.
