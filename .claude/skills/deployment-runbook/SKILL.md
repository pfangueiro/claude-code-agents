---
name: deployment-runbook
description: Deployment procedures, health checks, and rollback strategies. Use this skill when deploying applications, performing health checks, managing releases, or handling deployment failures. Provides systematic deployment workflows, verification scripts, and troubleshooting guides. Complements the devops-automation agent.
---

# Deployment Runbook

## Overview

This skill provides deployment procedures, automated health checks, and rollback strategies to ensure safe, reliable deployments. Use it to standardize deployment workflows and reduce deployment-related incidents.

## When to Use This Skill

- Planning production deployments
- Executing staged rollouts (canary, blue-green)
- Performing post-deployment health checks
- Rolling back failed deployments
- Troubleshooting deployment issues
- Establishing deployment best practices
- Complementing the **devops-automation agent** for deployments

## Pre-Deployment Checklist

Before any production deployment:

- [ ] **Code Review**: All changes reviewed and approved
- [ ] **Tests Pass**: CI/CD pipeline green
  - Unit tests: ✓
  - Integration tests: ✓
  - E2E tests: ✓
- [ ] **Database Migrations**: Tested in staging
  - Backward compatible
  - Rollback script prepared
- [ ] **Configuration**: Environment variables verified
  - Secrets rotated if needed
  - Feature flags configured
- [ ] **Monitoring**: Dashboards and alerts ready
  - Error tracking enabled
  - Performance monitoring active
  - Log aggregation configured
- [ ] **Communication**: Stakeholders notified
  - Deployment window announced
  - On-call engineer assigned
  - Rollback plan documented
- [ ] **Backups**: Recent backup verified
  - Database backed up < 1 hour ago
  - Backup restoration tested
- [ ] **Capacity**: Resources scaled appropriately
  - Auto-scaling configured
  - Rate limits reviewed
  - CDN cache warmed

## Deployment Strategies

> **Command convention — read once, it applies to every code block below.**
> This skill ships **exactly one** executable: `scripts/health_check.py`. Any command written
> in `<angle-brackets>` is a **placeholder for a tool you supply** — it is not shipped here, not
> inlined anywhere in this file, and there is no universal implementation of it (switching
> traffic, running migrations or restoring a database is entirely platform-specific).
> Substitute your own command before you rely on the procedure.
> Placeholders are deliberately written so a paste fails loudly (`no such file or directory`,
> non-zero exit) instead of appearing to succeed. Only `python3 scripts/health_check.py …`
> is a real, runnable command in this document.

### 1. Blue-Green Deployment

**Best for**: Zero-downtime deployments, easy rollbacks

**Process:**
1. Deploy to inactive (green) environment
2. Run health checks on green
3. Switch traffic from blue to green
4. Monitor for issues
5. Keep blue as instant rollback option

**Commands:** (`<…>` = placeholder you must supply; only the `health_check.py` line is shipped)
```bash
# Deploy to green environment
<your-deploy-tool> --env green

# Run health checks  (REAL — this script ships with the skill)
python3 scripts/health_check.py --env green

# Switch traffic (gradual)
<your-traffic-switch-tool> --from blue --to green --percentage 10
<your-traffic-switch-tool> --from blue --to green --percentage 50
<your-traffic-switch-tool> --from blue --to green --percentage 100

# If issues: instant rollback — see "Emergency rollback" under Rollback Procedures.
# Write your real command there NOW, not while the site is down.
<your-traffic-switch-tool> --from green --to blue --percentage 100
```

### 2. Canary Deployment

**Best for**: Risk-averse deployments, gradual rollouts

**Process:**
1. Deploy to small subset of servers (5-10%)
2. Monitor metrics closely
3. Gradually increase percentage
4. Roll back if metrics degrade

**Monitoring During Canary:**
- Error rate < 0.1% **absolute** — the Phase 4 healthy ceiling — *and* ≤ baseline + 0.05pp.
  The canary must never admit more error than a healthy deployment: an allowance of
  "baseline + 1%" would pass a canary running 10x the error rate the gate exists to
  protect, and it contradicts the > 99.9% success rate below (which *is* < 0.1% error).
  The > 1% figure in [Rollback Procedures](#when-to-rollback) is the emergency rollback
  trigger, not a canary pass mark.
- Response time < baseline + 10%
- Success rate > 99.9%

### 3. Rolling Deployment

**Best for**: Standard updates, resource-constrained environments

**Process:**
1. Take one instance out of load balancer
2. Deploy new version
3. Run health checks
4. Add back to load balancer
5. Repeat for remaining instances

## Deployment Workflow

### Phase 1: Pre-Deployment (T-30 minutes)

`<…>` = placeholder you must supply. The two `git` lines are real commands.
```bash
# 1. Verify staging environment
<your-staging-verify-tool>

# 2. Create deployment tag  (REAL — plain git)
git tag -a v1.2.3 -m "Release 1.2.3"
git push origin v1.2.3

# 3. Trigger production build
<your-build-tool> --tag v1.2.3

# 4. Backup database
<your-db-backup-tool> --environment production

# 5. Notify team
<your-notify-tool> "🚀 Starting deployment v1.2.3 in 30 minutes"
```

### Phase 2: Deployment (T-0)

Every line below is a `<…>` placeholder you must supply — none of these ship with the skill.
```bash
# 1. Enable maintenance mode (if needed)
<your-maintenance-mode-tool> --enable

# 2. Run database migrations
<your-migration-tool> --environment production

# 3. Deploy application
<your-deploy-tool> --environment production --version v1.2.3

# 4. Disable maintenance mode
<your-maintenance-mode-tool> --disable
```

### Phase 3: Post-Deployment Health Checks

> **`health_check.py` is a template, and it fails closed.** Only the API check is
> implemented; database, cache, metrics and external-services report
> `NOT IMPLEMENTED` and exit non-zero until you wire them to real probes. That is
> deliberate — a gate that cannot verify anything must not report success. Wire up
> the checks (and set real hosts in `ENVIRONMENTS`) before trusting it as a gate at
> any of the invocation sites below.

```bash
# Run health checks
python3 scripts/health_check.py --environment production

# Output BEFORE you implement the checks (expected, and correct) — verbatim, exit 1:
# ✗ API Health: API unreachable: HTTPSConnectionPool(host='api.example.com', port=443): ...
# ✗ Database: NOT IMPLEMENTED - no verification of Database connectivity was performed. ...
# ✗ Cache: NOT IMPLEMENTED - no verification of Cache layer was performed. ...
# ✗ Metrics: NOT IMPLEMENTED - no verification of Application metrics was performed. ...
# ✗ External Services: NOT IMPLEMENTED - no verification of External services was performed. ...
# ✗ SOME CHECKS FAILED (0/5 of the checks that ran passed)

# Once implemented and pointed at real hosts, a passing run reads (exit 0):
# ✓ API Health: API responding (7ms)          <- elapsed ms, NOT "HTTP 200"; the number varies
# ✓ Database: Database connectivity OK
# ✓ Cache: Cache layer accessible
# ✓ Metrics: Metrics within thresholds
# ✓ External Services: <your string — the script ships none for this check>
# ✓ ALL CHECKS PASSED (5/5)
```

Four of those five strings — `API responding (<n>ms)`, `Database connectivity OK`, `Cache layer
accessible`, `Metrics within thresholds` — are the ones in `health_check.py`'s own implementation
snippets. `check_external_services()` ships **no** success string: it only returns the fail-closed
`_not_implemented(...)` message, so whoever implements it chooses the wording. The API line reports
measured latency, never the status code. Match on the exit code, not on any of this text.

### Phase 4: Monitoring (T+30 minutes)

Monitor these metrics:

**Application Metrics:**
- Error rate: < 0.1%
- Response time (p95): < 200ms
- Request throughput: within expected range
- Success rate: > 99.9%

**Infrastructure Metrics:**
- CPU utilization: < 70%
- Memory usage: < 80%
- Disk I/O: normal patterns
- Network latency: < 50ms

**Business Metrics:**
- Conversion rate: no significant drop
- User signups: within expected range
- Transaction volume: normal patterns

## Rollback Procedures

### When to Rollback

Rollback immediately if:
- Error rate > 1%
- Critical functionality broken
- Data corruption detected
- Security vulnerability introduced
- Performance degradation > 50%

### Rollback Methods

#### Method 1: Traffic Switch (Fastest) — "Emergency rollback"

> **🛑 There is no shipped rollback command. `<your-traffic-switch-tool>` is a placeholder.**
> This skill cannot know how your traffic is steered — a Kubernetes Service selector, an ALB
> target-group weight, a DNS record and an nginx upstream are four different commands, and
> guessing one here would be worse than admitting there is none.
> **Fill in the real command for your platform below, and verify it in staging, BEFORE an
> incident.** Discovering mid-outage that the fastest rollback path is a placeholder is the
> failure this warning exists to prevent.

```bash
# Blue-green: instant rollback — PLACEHOLDER, replace with your platform's command
<your-traffic-switch-tool> --from green --to blue --percentage 100

# Verification  (REAL — this script ships with the skill)
python3 scripts/health_check.py --environment production
```

#### Method 2: Version Revert

```bash
# Deploy previous version — PLACEHOLDER
<your-deploy-tool> --environment production --version v1.2.2

# Run health checks  (REAL — this script ships with the skill)
python3 scripts/health_check.py --environment production
```

#### Method 3: Database Rollback

```bash
# If migrations were applied — PLACEHOLDER
<your-migration-rollback-tool> --environment production --steps 1

# Restore from backup (last resort) — PLACEHOLDER
<your-db-restore-tool> --backup latest --environment production
```

### Post-Rollback

1. **Verify system health**
   ```bash
   python3 scripts/health_check.py --environment production
   ```

2. **Notify stakeholders** (placeholder — supply your own notifier)
   ```bash
   <your-notify-tool> "⚠️ Deployment v1.2.3 rolled back. System stable on v1.2.2"
   ```

3. **Create postmortem**
   - What went wrong?
   - Why didn't we catch it?
   - How do we prevent recurrence?

## Health Check Script

Use the included health check script:

```bash
# Run all checks
python3 scripts/health_check.py --env production

# Run specific check
python3 scripts/health_check.py --env production --check api

# Verbose output
python3 scripts/health_check.py --env production --verbose
```

`--env` accepts any key of `ENVIRONMENTS` in the script: `production`, `staging`, and the
blue-green slots `blue` and `green` (the choices are derived from that dict, so the accepted
set cannot drift from the configured one).

**Exit codes — a CI gate must distinguish these. Only `0` is a pass:**

| Code | Meaning |
|------|---------|
| `0`  | FULL run, every check passed — the only result that green-lights a deploy |
| `1`  | at least one check that RAN failed |
| `2`  | USAGE error (unknown `--env`, bad flag): the invocation was rejected, so NO check ran and nothing was verified |
| `3`  | PARTIAL run (`--check`): everything that ran passed, but not every check ran, so nothing was gated |
| `130`| interrupted |

`2` and `3` both mean *the deployment was not gated* and differ only in why. They are kept
distinct on purpose: a usage error must never share a code with a "what ran passed" result,
or a gate reading that code would score a mistyped command as a success-ish state.

See `scripts/health_check.py` for implementation.

## Troubleshooting Guide

### Issue: Deployment Hangs

**Symptoms:**
- Deployment script doesn't complete
- Services not starting

**Diagnosis:**
```bash
# Check service logs
kubectl logs -f deployment/app-name

# Check events
kubectl get events --sort-by='.lastTimestamp'
```

**Resolution:**
- Increase timeout values
- Check resource constraints
- Verify image pull secrets

### Issue: High Error Rate Post-Deployment

**Symptoms:**
- Error rate spike
- 500 errors in logs

**Diagnosis:**
```bash
# Check application logs
tail -f /var/log/app/error.log

# Check error distribution
grep "ERROR" /var/log/app/* | awk '{print $NF}' | sort | uniq -c | sort -nr
```

**Resolution:**
- Check configuration changes
- Verify environment variables
- Review recent code changes
- Consider immediate rollback

### Issue: Database Connection Failures

**Symptoms:**
- "Connection refused" errors
- Timeout errors

**Diagnosis:**
```bash
# Test database connectivity (wire up check_database first — it fails closed until you do)
python3 scripts/health_check.py --env production --check database

# Check connection pool
psql -h db-host -U user -c "SELECT * FROM pg_stat_activity;"
```

**Resolution:**
- Verify connection strings
- Check firewall rules
- Increase connection pool size
- Verify credentials

## Communication Templates

### Pre-Deployment Announcement

```
🚀 **Production Deployment Scheduled**

**Version**: v1.2.3
**Time**: 2024-01-15 14:00 UTC (30 minutes)
**Duration**: ~15 minutes
**Impact**: No expected downtime

**Changes**:
- Feature: New user dashboard
- Fix: Payment processing bug
- Performance: API response time improvements

**Rollback Plan**: Blue-green switch (instant)
**On-Call**: @engineer-name
```

### Deployment Success

```
✅ **Deployment Complete**

**Version**: v1.2.3
**Status**: Successful
**Duration**: 12 minutes

**Health Checks**: All passing ✓
**Metrics**: Within normal range
**Next Check**: T+30 minutes

Monitoring dashboard: [link]
```

### Deployment Rollback

```
⚠️ **Deployment Rolled Back**

**Version**: v1.2.3 → v1.2.2 (rollback)
**Reason**: Elevated error rate (2.1%)
**Status**: System stable on v1.2.2

**Action Items**:
- [ ] Root cause analysis
- [ ] Fix identified issue
- [ ] Re-test in staging
- [ ] Schedule re-deployment

Incident report: [link]
```

## Resources

### scripts/
- **health_check.py**: Deployment health-check harness. **Template — only the API check is
  implemented**; the rest fail closed with `NOT IMPLEMENTED` until you wire them up.

That is the **only** executable this skill ships. Do not cite a resource file unless it exists on
disk (`validate.sh` asserts this).

Every other command in this document is a `<angle-bracketed>` **placeholder for a tool you
supply** — not shipped, and not inlined elsewhere in this file, because each one is
platform-specific and this skill cannot know your platform:

- `<your-deploy-tool>` · `<your-traffic-switch-tool>` · `<your-staging-verify-tool>`
- `<your-build-tool>` · `<your-db-backup-tool>` · `<your-db-restore-tool>`
- `<your-migration-tool>` · `<your-migration-rollback-tool>`
- `<your-maintenance-mode-tool>` · `<your-notify-tool>`

Earlier revisions wrote these as bare `./<name>.sh` invocations, which read as runnable commands
that do not exist — including the emergency rollback. They are bracketed now so a paste fails
loudly instead of looking like it worked.

## Best Practices

1. **Always deploy during low-traffic windows**
2. **Never deploy on Fridays** (unless critical hotfix)
3. **Keep deployments small** (< 200 lines changed)
4. **Monitor for 30+ minutes** post-deployment
5. **Document every rollback** with postmortem
6. **Test rollback procedure** in staging first
7. **Use feature flags** for risky changes
8. **Automate health checks** (don't rely on manual verification)

## Quick Reference

**Emergency Rollback** — ⚠️ **placeholder, NOT a runnable command.** Nothing here switches
traffic; substitute your platform's command (see Rollback Procedures → Method 1: Traffic
Switch) and have it written down *before* the incident:
```bash
<your-traffic-switch-tool> --from green --to blue --percentage 100
```

**Health Check** (real — the one shipped executable):
```bash
python3 scripts/health_check.py --env production
```

**View Logs:**
```bash
kubectl logs -f deployment/app-name --tail=100
```

**Check Metrics:**
```bash
curl https://metrics.example.com/api/health
```
