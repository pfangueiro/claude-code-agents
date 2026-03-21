---
name: sre-runbooks
description: SRE operational runbooks, on-call handbook, blameless postmortem templates, SLI/SLO/error budget definitions, toil reduction framework, capacity planning, and chaos engineering playbook. Auto-activates on runbook, on-call, postmortem, error budget, SLO, SLA, capacity planning, chaos engineering, incident review, toil, game day.
---

# SRE Runbooks

## Overview

Operational runbook templates and SRE practices for production reliability. Covers on-call workflows, incident response, postmortems, capacity planning, and chaos engineering.

## SLI/SLO Definition Template

```yaml
service: payment-api
owner: payments-team
tier: critical

slis:
  availability:
    description: "Ratio of successful HTTP responses (non-5xx) to total responses"
    query: "sum(rate(http_requests_total{service='payment-api', status!~'5..'}[5m])) / sum(rate(http_requests_total{service='payment-api'}[5m]))"
    good_event: "HTTP response with status < 500"
    valid_event: "All HTTP responses (excluding health checks)"

  latency:
    description: "Ratio of requests served faster than 300ms"
    query: "sum(rate(http_request_duration_seconds_bucket{service='payment-api', le='0.3'}[5m])) / sum(rate(http_request_duration_seconds_count{service='payment-api'}[5m]))"
    threshold: 300ms
    percentile: p99

slos:
  availability:
    target: 99.95%
    window: 30d
    error_budget: 21.9 minutes/month

  latency:
    target: 99.0%
    window: 30d
    description: "99% of requests complete within 300ms"

error_budget_policy:
  budget_available:  # >50% remaining
    - "Ship features normally"
    - "Conduct chaos experiments"
    - "Allow risky deployments with rollback plan"
  budget_warning:    # 20-50% remaining
    - "Prioritize reliability work alongside features"
    - "Review recent incidents for patterns"
    - "No chaos experiments without team approval"
  budget_critical:   # <20% remaining
    - "Freeze non-critical deployments"
    - "Mandatory postmortem for any new incident"
    - "Dedicated reliability sprint next cycle"
  budget_exhausted:  # 0% remaining
    - "Complete change freeze for this service"
    - "All engineering effort on reliability"
    - "Escalate to engineering leadership"
    - "Resume normal operations only when budget recovers"
```

## On-Call Handbook

### Rotation Structure

```
Primary:    First responder, handles all pages
Secondary:  Backup if primary doesn't respond in 15 minutes
Escalation: Engineering manager → VP Engineering (for P1 only)
Rotation:   Weekly, handoff every Monday 10:00 AM
```

### On-Call Expectations

| Aspect | Requirement |
|--------|------------|
| Acknowledge page | Within 5 minutes |
| Begin triage | Within 15 minutes |
| Update status page | Within 20 minutes (P1/P2) |
| Escalate if stuck | After 30 minutes without progress |
| Max incidents/shift | 2 per 12-hour shift (exceeding = process problem) |
| Compensation | On-call stipend + per-incident for off-hours |

### Handoff Template

```
## On-Call Handoff: [date]

### Active Issues
- [Issue]: [status], [next action], [ETA]

### Recent Changes
- [deployment/config change]: [when], [who], [rollback plan]

### Upcoming Risks
- [planned maintenance]: [when], [impact], [owner]
- [known issue]: [workaround], [fix ETA]

### Notes for Next Shift
- [anything unusual observed]
```

### Escalation Matrix

| Severity | Description | Response | Escalation |
|----------|-------------|----------|------------|
| **P1** | Service fully down, data loss risk | Page immediately | Eng manager at 15min, VP at 30min |
| **P2** | Degraded service, partial impact | Page within 15min | Eng manager at 30min |
| **P3** | Minor impact, workaround available | Ticket, next business day | Team lead at 48h |
| **P4** | Cosmetic, no user impact | Backlog | N/A |

## Infrastructure Runbooks

### High CPU on Nodes

```
Symptoms: Node CPU >85%, pod throttling, slow responses
Alert: NodeCPUHigh

Diagnosis:
1. Identify top CPU consumers:
   kubectl top pods --all-namespaces --sort-by=cpu | head -20

2. Check if it's one pod or many:
   - One pod: check for CPU-intensive operation, missing limits, infinite loop
   - Many pods: check for traffic spike, external dependency timeout causing retries

3. Check HPA status:
   kubectl get hpa --all-namespaces

Mitigation:
- Immediate: Scale out nodes (Karpenter will auto-provision if configured)
- Short-term: Increase CPU limits for the affected pod, add HPA if missing
- Long-term: Profile the application, optimize hot paths, add caching

Verification:
- kubectl top nodes → CPU <70%
- No pods in Throttling state
- Response latency returns to normal
```

### Pod CrashLoopBackOff

```
Symptoms: Pod restarts repeatedly, service degraded
Alert: PodCrashLooping

Diagnosis:
1. Check pod events:
   kubectl describe pod POD -n NAMESPACE | tail -30

2. Check previous container logs:
   kubectl logs POD -n NAMESPACE --previous

3. Common causes:
   - OOMKilled → check: kubectl get pod POD -o jsonpath='{.status.containerStatuses[0].lastState}'
   - Application error → check logs for stack trace
   - Missing config/secret → check: kubectl get pod POD -o yaml | grep -A5 envFrom
   - Failed health probe → check probe config vs actual startup time
   - Permission denied → check securityContext, serviceAccount

Mitigation:
- OOMKilled: Increase memory limits (check actual usage first)
- App error: Fix code, rollback deployment if recent change
- Missing config: Create/fix ConfigMap or Secret
- Probe failure: Increase initialDelaySeconds, adjust thresholds
- Permission: Fix RBAC, adjust securityContext

Verification:
- kubectl get pod POD → Running, 0 restarts in last 10 min
- kubectl logs POD → no error messages
- Service responding to health checks
```

### Database Connection Pool Exhaustion

```
Symptoms: "too many connections", application timeouts, 503 errors
Alert: DatabaseConnectionPoolExhausted

Diagnosis:
1. Check active connections:
   SELECT count(*), state FROM pg_stat_activity GROUP BY state;

2. Check for idle-in-transaction:
   SELECT pid, query, state, query_start FROM pg_stat_activity
   WHERE state = 'idle in transaction' AND query_start < NOW() - INTERVAL '5 minutes';

3. Check for long-running queries:
   SELECT pid, query, state, NOW() - query_start AS duration
   FROM pg_stat_activity WHERE state = 'active' ORDER BY duration DESC LIMIT 10;

4. Check application pool settings vs database max_connections

Mitigation:
- Immediate: Kill idle-in-transaction connections:
  SELECT pg_terminate_backend(pid) FROM pg_stat_activity
  WHERE state = 'idle in transaction' AND query_start < NOW() - INTERVAL '10 minutes';
- Short-term: Increase pool size or max_connections (with RAM check)
- Long-term: Fix connection leaks in application, add connection timeouts, use PgBouncer

Verification:
- Active connections < 80% of max_connections
- No idle-in-transaction connections older than 1 minute
- Application 503 errors resolved
```

### Certificate Expiration

```
Symptoms: TLS errors, browser warnings, API connection failures
Alert: CertificateExpiringSoon (fires at 30 days, 7 days, 1 day)

Diagnosis:
1. Check certificate expiry:
   echo | openssl s_client -connect HOST:443 2>/dev/null | openssl x509 -noout -dates

2. Check Kubernetes TLS secrets:
   kubectl get secret TLS_SECRET -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates

3. Check cert-manager status (if used):
   kubectl get certificates --all-namespaces
   kubectl describe certificate CERT_NAME -n NAMESPACE

Mitigation:
- cert-manager: Check Certificate resource, Issuer status, fix any errors
- Manual: Renew certificate, update Kubernetes secret, restart ingress controller
- ACM (AWS): Certificates auto-renew — check DNS validation records exist

Prevention:
- Use cert-manager with Let's Encrypt for automatic renewal
- Alert at 30 days, 7 days, 1 day before expiry
- Never use self-signed certificates in production
```

### Node NotReady in Kubernetes

```
Symptoms: Pods evicted, scheduling failures, workload disruption
Alert: KubernetesNodeNotReady

Diagnosis:
1. Check node status:
   kubectl get nodes
   kubectl describe node NODE_NAME | grep -A10 Conditions

2. Check kubelet:
   ssh NODE → journalctl -u kubelet --since "30 minutes ago" | tail -50

3. Common causes:
   - Disk pressure: df -h (>85% = kubelet marks NotReady)
   - Memory pressure: free -m (OOM killer active)
   - Network: can node reach API server? curl -k https://APISERVER:6443/healthz
   - kubelet crash: systemctl status kubelet

Mitigation:
- Disk pressure: Clean up logs, images: crictl rmi --prune
- Memory: Identify OOM-killed processes, restart heavy workloads
- Network: Check security groups, route tables, VPN
- kubelet: Restart kubelet, check certificates

- If node won't recover:
  kubectl drain NODE_NAME --ignore-daemonsets --delete-emptydir-data
  (Karpenter will replace the node automatically)

Verification:
- kubectl get nodes → all Ready
- Pods rescheduled and running on healthy nodes
- No PodDisruptionBudget violations
```

## Blameless Postmortem Template

```markdown
# Postmortem: [Incident Title]

**Date**: YYYY-MM-DD  **Severity**: P1/P2/P3  **Duration**: X hours Y minutes
**Authors**: [names]  **Reviewers**: [names]  **Status**: Draft / Action Items In Progress / Closed

## Executive Summary
[2-3 sentences: what happened, impact, resolution]

## Impact
- **Users affected**: [count or percentage]
- **Duration**: [minutes]
- **Revenue impact**: [estimate or "not applicable"]
- **SLO impact**: [X% of error budget consumed]
- **Data loss**: [yes/no, details if yes]

## Timeline (all times in UTC)

| Time | Event |
|------|-------|
| HH:MM | Triggering event (deployment, config change, traffic spike) |
| HH:MM | First alert fired: [alert name] |
| HH:MM | On-call acknowledged |
| HH:MM | Initial triage: [what was checked] |
| HH:MM | Root cause identified |
| HH:MM | Mitigation applied: [what was done] |
| HH:MM | Service partially recovered |
| HH:MM | Service fully recovered |
| HH:MM | All-clear communicated |

## Root Cause Analysis

### 5 Whys
1. **Why** did the service go down? → [proximate cause]
2. **Why** did that happen? → [intermediate cause]
3. **Why** did that happen? → [deeper cause]
4. **Why** did that happen? → [systemic cause]
5. **Why** did that happen? → [ROOT CAUSE]

### Technical Details
[Detailed technical explanation with evidence: logs, metrics, code references]

## Contributing Factors
- [Factor that amplified the impact but isn't the root cause]
- [Factor that delayed detection or response]

## What Went Well
- [Things that worked during the incident]
- [Effective responses or tools]

## What Could Be Improved
- [Detection gaps]
- [Response delays]
- [Communication issues]
- [Tool limitations]

## Action Items

| # | Action | Type | Owner | Priority | Due | Status |
|---|--------|------|-------|----------|-----|--------|
| 1 | [Specific fix for root cause] | Prevent | [name] | P1 | [date] | Open |
| 2 | [Detection improvement] | Detect | [name] | P1 | [date] | Open |
| 3 | [Process improvement] | Process | [name] | P2 | [date] | Open |
| 4 | [Runbook update] | Document | [name] | P2 | [date] | Open |

## Lessons Learned
- [Systemic insight applicable beyond this incident]
- [Pattern to watch for in similar systems]
```

**Postmortem rules:**
- Focus on systems, not individuals
- Every P1/P2 gets a postmortem within 5 business days
- Action items have owners, priorities, and deadlines
- Close postmortem only when all P1 action items are complete
- Share with entire engineering org to spread learnings

## Capacity Planning Template

```markdown
## Capacity Plan: [Service Name]

**Current baseline** (date: YYYY-MM-DD):
- Peak QPS: [value]
- Average CPU utilization at peak: [%]
- Average memory utilization at peak: [%]
- Current replica count: [N]
- Current node count: [N]

**Growth projection**:
- Monthly growth rate: [%]
- Projected peak QPS in 3 months: [value]
- Projected peak QPS in 6 months: [value]
- Seasonal multiplier: [e.g., 3x for Black Friday]

**Scaling limits**:
- Max replicas (HPA): [N]
- Max nodes (Karpenter/ASG): [N]
- Database max connections: [N]
- Known bottleneck: [component] at [threshold]

**Action required by [date]**:
- [ ] Increase [resource] from [current] to [target]
- [ ] Optimize [bottleneck] before reaching [threshold]
- [ ] Load test at [projected peak * 1.5]
```

## Chaos Engineering Playbook

### Pre-Requisites
- SLOs defined and monitored
- Error budget available (>20%)
- Runbooks exist for expected failure modes
- Team has agreed to the experiment scope

### Experiment Template

```markdown
## Chaos Experiment: [Title]

**Hypothesis**: If [failure condition], the system should [expected behavior] within [time].

**Steady state**: [metrics that define "normal" — SLIs within SLO]

**Method**: [What to break]
- Scope: [namespace/service/node]
- Duration: [how long]
- Blast radius: [what's affected]

**Abort conditions**: [when to stop immediately]
- SLI drops below [threshold]
- Error rate exceeds [%]
- Customer reports

**Results**:
- Hypothesis confirmed? [yes/no]
- Unexpected behavior: [description]
- Action items: [list]
```

### Common Experiments

| Experiment | Tool | Tests |
|-----------|------|-------|
| Kill random pod | `kubectl delete pod` | Auto-recovery, PDB enforcement |
| Inject latency | Chaos Mesh / Litmus | Circuit breakers, timeouts, retries |
| Network partition | Chaos Mesh | Graceful degradation, fallbacks |
| Fill disk | `dd if=/dev/zero` | Alerts, log rotation, eviction |
| DNS failure | Block DNS resolution | Caching, error handling, fallbacks |
| Dependency unavailable | Block egress to service | Circuit breaker, cached responses |

### Game Day Planning

1. **Schedule**: 2 hours, business hours, all relevant engineers present
2. **Scope**: One service or failure domain per game day
3. **Run**: Execute experiments, observe responses, take notes
4. **Debrief**: Immediately after — what worked, what didn't, action items
5. **Cadence**: Monthly for critical services, quarterly for others

## Toil Reduction Framework

### Identify Toil

Toil is work that is: manual, repetitive, automatable, reactive, scales with service growth, has no enduring value.

### Catalog Template

| Task | Frequency | Duration | Automatable? | Priority |
|------|-----------|----------|-------------|----------|
| Restart pods after deploy | Daily | 10 min | Yes | High |
| Rotate certificates | Monthly | 30 min | Yes (cert-manager) | High |
| Clean up old logs | Weekly | 15 min | Yes (logrotate) | Medium |
| Review alerts | Daily | 20 min | Partially (tune alerts) | Medium |
| Manual scaling | Variable | 15 min | Yes (HPA/Karpenter) | High |

### Target
- SREs spend <50% time on toil, >50% on engineering projects
- Track toil hours per sprint
- Prioritize automation by: `frequency * duration * error_risk`
