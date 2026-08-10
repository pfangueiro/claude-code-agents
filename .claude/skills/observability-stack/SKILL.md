---
name: observability-stack
description: Observability architecture with OpenTelemetry, Prometheus, Grafana, and structured logging. Covers RED/USE metrics, SLI/SLO monitoring, multi-window burn-rate alerting, dashboard design, and distributed tracing. Auto-activates on monitoring, observability, metrics, alerting, dashboard, Prometheus, Grafana, OpenTelemetry, tracing, logging, SLI, SLO.
---

# Observability Stack

## Overview

Production observability using the three pillars (metrics, logs, traces) with OpenTelemetry as the collection standard. Covers metric design, alerting strategies, dashboard patterns, and cost management.

## The Three Pillars

| Pillar | What | Tool Stack | When |
|--------|------|-----------|------|
| **Metrics** | Numeric time-series data | Prometheus + Grafana | Trend detection, alerting, capacity |
| **Logs** | Structured event records | Loki / ELK / CloudWatch | Debugging, audit trails, forensics |
| **Traces** | Request flow across services | Tempo / Jaeger / X-Ray | Latency analysis, dependency mapping |

All three must be **correlated** via trace context (trace_id, span_id) for effective debugging.

## Metric Design

### RED Method (Service-Level)

Measure what **users experience**. Apply to every service endpoint.

```promql
# Rate — requests per second
rate(http_requests_total{service="api"}[5m])

# Errors — error percentage
rate(http_requests_total{service="api", status=~"5.."}[5m])
/ rate(http_requests_total{service="api"}[5m]) * 100

# Duration — p99 latency
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{service="api"}[5m]))
```

### USE Method (Infrastructure-Level)

Measure what the **infrastructure is doing**. Apply to every resource.

| Resource | Utilization | Saturation | Errors |
|----------|------------|------------|--------|
| **CPU** | `node_cpu_seconds_total` | `node_load15` / num_cpus | — |
| **Memory** | `node_memory_MemAvailable_bytes` | `node_memory_SwapFree_bytes` | OOM events |
| **Disk** | `node_filesystem_avail_bytes` | `node_disk_io_time_weighted_seconds_total` | `node_disk_io_errors` |
| **Network** | `node_network_transmit_bytes_total` | `node_network_transmit_drop_total` | `node_network_transmit_errs_total` |
| **K8s Pod** | CPU/mem requests vs limits | Throttling, evictions | CrashLoopBackOff count |

### Naming Convention

Follow Prometheus naming: `<namespace>_<name>_<unit>_<suffix>`

```
http_requests_total           # counter — always _total suffix
http_request_duration_seconds # histogram — always include unit
http_requests_in_flight       # gauge — current value
```

## SLI/SLO Monitoring

### Define SLIs as Prometheus Recording Rules

```yaml
groups:
  - name: sli_rules
    # Evaluate no faster than 1m: the 3d-range rule below is expensive to recompute.
    interval: 1m
    rules:
      # Every SLI is grouped `by (service)` — the dimension the SLO is defined on.
      #
      # An ungrouped `sum(rate(...))` collapses the whole fleet into one number and
      # DILUTES a single service's outage below every burn-rate threshold. With nine
      # healthy services at 100 req/min and one 10 req/min service that is 100% down,
      # the fleet error ratio is 10/910 = 0.011 — under the 0.0144 fast-burn
      # threshold. The service is completely dead and nobody is paged.
      #
      # The `or 0 * ...` fallback is not decoration. Binary operators drop series with
      # no match on the other side, so a service serving *only* 5xx has no
      # `status!~"5.."` numerator, is dropped by the division, and vanishes from the
      # SLI — the total-outage case is precisely the one that disappears. The fallback
      # pins those services to 0 instead of absent. Grouping alone does NOT fix this;
      # both halves are required. (Verified with `promtool test rules` — see below.)

      # Availability SLI: ratio of successful requests, per service
      - record: sli:availability:ratio_rate5m
        expr: |
          (
            sum by (service) (rate(http_requests_total{status!~"5.."}[5m]))
            or 0 * sum by (service) (rate(http_requests_total[5m]))
          )
          / sum by (service) (rate(http_requests_total[5m]))

      # Long-window availability SLIs — REQUIRED by the multi-window burn-rate
      # alerts below. Every window an alert references must be recorded here:
      # Prometheus returns an empty vector for an unknown metric name, so an
      # alert ANDing an undefined rule silently never fires and logs no error.
      # Keep the grouping identical across windows: `and` matches on the full label
      # set, so a rule grouped differently from its partner never intersects.
      - record: sli:availability:ratio_rate30m
        expr: |
          (
            sum by (service) (rate(http_requests_total{status!~"5.."}[30m]))
            or 0 * sum by (service) (rate(http_requests_total[30m]))
          )
          / sum by (service) (rate(http_requests_total[30m]))

      - record: sli:availability:ratio_rate1h
        expr: |
          (
            sum by (service) (rate(http_requests_total{status!~"5.."}[1h]))
            or 0 * sum by (service) (rate(http_requests_total[1h]))
          )
          / sum by (service) (rate(http_requests_total[1h]))

      - record: sli:availability:ratio_rate6h
        expr: |
          (
            sum by (service) (rate(http_requests_total{status!~"5.."}[6h]))
            or 0 * sum by (service) (rate(http_requests_total[6h]))
          )
          / sum by (service) (rate(http_requests_total[6h]))

      # 3d window needs >= 3d retention; evaluate this group no faster than
      # `interval: 1m` — long-range rate() is expensive to recompute.
      - record: sli:availability:ratio_rate3d
        expr: |
          (
            sum by (service) (rate(http_requests_total{status!~"5.."}[3d]))
            or 0 * sum by (service) (rate(http_requests_total[3d]))
          )
          / sum by (service) (rate(http_requests_total[3d]))

      # Latency SLI: ratio of requests faster than 300ms, per service
      - record: sli:latency:ratio_rate5m
        expr: |
          (
            sum by (service) (rate(http_request_duration_seconds_bucket{le="0.3"}[5m]))
            or 0 * sum by (service) (rate(http_request_duration_seconds_count[5m]))
          )
          / sum by (service) (rate(http_request_duration_seconds_count[5m]))
```

### Error Budget Calculation

```promql
# Error budget remaining (30-day window), for one service.
# The SLI is recorded `by (service)`, so name the service you mean — left
# unqualified this returns one series per service, never a fleet-wide number.
1 - (
  (1 - avg_over_time(sli:availability:ratio_rate5m{service="api"}[30d]))
  / (1 - 0.999)  # SLO target
)
```

### Multi-Window Multi-Burn-Rate Alerts

Google SRE recommended approach — alert on budget consumption rate, not raw thresholds.

```yaml
groups:
  - name: slo_alerts
    # Each operand below is a per-service vector (the SLIs are recorded
    # `by (service)`), and `1 - <vector>` keeps the vector's labels while dropping
    # __name__. Both sides of every `and` therefore carry exactly `{service="..."}`
    # and intersect per service, so ONE service breaching its own budget pages on
    # its own. If the two windows in an `and` are ever grouped differently, the
    # label sets stop matching and the alert can never fire.
    rules:
      # Fast burn: 2% budget consumed in 1 hour → page
      - alert: SLOBurnRateCritical
        expr: |
          (
            1 - sli:availability:ratio_rate1h > (14.4 * (1 - 0.999))
            and
            1 - sli:availability:ratio_rate5m > (14.4 * (1 - 0.999))
          )
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High error budget burn rate (fast burn) for service {{ $labels.service }}"
          runbook_url: "https://wiki/runbooks/slo-burn-rate"

      # Slow burn: 5% budget consumed in 6 hours → page
      - alert: SLOBurnRateWarning
        expr: |
          (
            1 - sli:availability:ratio_rate6h > (6 * (1 - 0.999))
            and
            1 - sli:availability:ratio_rate30m > (6 * (1 - 0.999))
          )
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Elevated error budget burn rate (slow burn) for service {{ $labels.service }}"
          runbook_url: "https://wiki/runbooks/slo-burn-rate"

      # Gradual burn: 10% budget consumed in 3 days → ticket
      - alert: SLOBurnRateTicket
        expr: |
          (
            1 - sli:availability:ratio_rate3d > (1 * (1 - 0.999))
            and
            1 - sli:availability:ratio_rate6h > (1 * (1 - 0.999))
          )
        for: 1h
        labels:
          severity: ticket
        # A ticket-severity alert reaches someone with no pager context and no
        # incident channel, so it needs MORE explanation than the page, not less.
        # Annotations are what turns a row in a queue into something actionable.
        annotations:
          summary: "Gradual error budget burn for service {{ $labels.service }} — 10% of the 30d budget in 3 days"
          description: >-
            3d error ratio for {{ $labels.service }} is {{ $value | humanizePercentage }},
            above the 1x sustainable burn for a 99.9% SLO. Not urgent, but at this pace the
            30d budget is exhausted before the window closes. Triage in business hours.
          runbook_url: "https://wiki/runbooks/slo-burn-rate"

      # Companion to all three burn-rate alerts: catches the outage a RATIO cannot
      # see (see "Zero Traffic Is the Blind Spot" below). Self-inventorying — the
      # long left-hand window is the list of services that are supposed to be serving.
      #   left  = served traffic at some point in the last day
      #   right = serving traffic now
      # `unless` keeps left-hand elements with no exactly-matching label set on the
      # right, so a service that went flat (rate 0, filtered out by `> 0`) OR vanished
      # (no series at all in the 10m window) survives the filter and fires.
      - alert: ServiceTrafficAbsent
        expr: |
          (
            sum by (service) (rate(http_requests_total[1d])) > 0
            unless
            sum by (service) (rate(http_requests_total[10m])) > 0
          )
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.service }} is serving no traffic — its SLO alerts are blind, not green"
          description: >-
            No requests in 10m for a service that served traffic within the last day.
            The burn-rate alerts above divide by zero here and cannot fire, so treat a
            quiet SLO dashboard for {{ $labels.service }} as unverified, not healthy.
          runbook_url: "https://wiki/runbooks/traffic-absent"
```

### Zero Traffic Is the Blind Spot in Every Ratio SLI

A burn-rate alert divides errors by requests, so it has nothing to say when there are
no requests. Two shapes of **total** outage therefore read as perfectly healthy:

| Failure | What the SLI evaluates to | Why the alert stays silent |
|---|---|---|
| Process up, receiving nothing (load balancer misroute, upstream dead, consumer stopped) | numerator and denominator are both `rate() == 0`, so the ratio is `0 / 0` | Prometheus arithmetic follows [IEEE 754](https://prometheus.io/docs/prometheus/latest/querying/operators/), so `0/0` is `NaN` and `1 - NaN` is `NaN`. Every ordered comparison against `NaN` is false, so `> threshold` never matches and the alert has no series to fire on |
| Target gone entirely (pod deleted, job dropped from discovery) | selectors match nothing, so the recording rule emits **no series at all** | An alert over an empty vector never fires and logs nothing; the panel renders "No data" |

The `or 0 * sum(...)` guard in the recording rules above does **not** cover this. It
supplies a `0` numerator when a service served no *non-5xx* requests. It cannot supply
a denominator when the service served no requests at all.

That is why `ServiceTrafficAbsent` is in the group above rather than described here as
an optional extra — copying the burn-rate rules without it ships the blind spot. Know
its edges:

- **The self-inventory expires.** The `[1d]` left-hand window is the alert's entire
  memory of which services exist. Once a service has been silent longer than that
  window it drops off the left-hand side, the alert **resolves itself**, and the
  outage carries on unwatched. Set that window to the longest outage you must still
  be paged for, and pay the retention cost.
- **A service that has never served traffic is invisible** — there is no left-hand
  element to keep. For a service you must never lose, name it explicitly:

  ```promql
  absent(http_requests_total{service="checkout"})
  ```

  `absent()` returns a 1-element vector only when its argument matches nothing, and it
  derives the output labels from **equality matchers only** — `absent(sum(...))`
  returns a label-less `{}`, and a `=~` matcher is dropped. Keep it a plain selector,
  and add one rule per service you refuse to lose silently.
- **`up == 0` is not a substitute.** That reports a target Prometheus cannot scrape;
  this reports a healthy, scraped process that nothing is talking to. They fail
  independently — alert on both.
- **Low traffic breaks the ratio too, in the opposite direction.** At 5 requests in a
  window a single error is a 20% error rate, and fast burn trips on statistical noise.
  Either add a minimum-volume term to the burn-rate `and` chain —
  `and sum by (service) (rate(http_requests_total[5m])) > 0.1` (≈30 requests per 5m) —
  or move low-volume services off ratio alerting onto an absolute error-count alert.
  Adding the volume term makes the alert *more* dependent on `ServiceTrafficAbsent`,
  since it explicitly excludes the quiet case.

Like every other alert here, this one is only real once a unit test proves it fires
(next section). Drive it with a series that stops mid-test — `values: '0+100x30 _x60'`,
where [`_` is a missing sample](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/) —
and assert `ServiceTrafficAbsent` in `exp_alerts` after the gap.

### Verify the Rules Actually Fire

**A silent alert and a healthy service look identical.** A PromQL selector naming a
metric that was never recorded — a typo, a deleted recording rule, a window nobody
recorded — returns an **empty vector**. Empty is not an error: the alert evaluates
to zero series, never fires, logs nothing, and the panel renders "No data", which
reads as green. The failure mode of a broken SLO alert is silence, and silence is
exactly what a healthy system produces.

`promtool check rules` **cannot catch this.** It parses and type-checks rule files
with no TSDB attached, so it has no way to know whether any series ever satisfies a
selector. It passes an ungrouped, fleet-diluted SLI and a misspelled metric name
with the same cheerful `SUCCESS`. Treat exit 0 as "the YAML is well-formed", never
as "this alert can fire".

The only check that catches both is a
[rule unit test](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/),
which synthesizes a TSDB and asserts on the alerts produced:

```yaml
# slo_test.yml
rule_files:
  - sli_rules.yml
  - slo_alerts.yml
evaluation_interval: 1m
tests:
  - interval: 1m
    input_series:
      # One busy healthy service...
      - series: 'http_requests_total{service="api", status="200"}'
        values: '0+1000x120'
      # ...and one small service that is 100% down. Fleet-wide the error ratio is
      # only 10/1010 = 0.0099, UNDER the 0.0144 fast-burn threshold — so with an
      # ungrouped SLI this test fails with `got:[]` and checkout dies unnoticed.
      - series: 'http_requests_total{service="checkout", status="500"}'
        values: '0+10x120'
    alert_rule_test:
      - eval_time: 90m
        alertname: SLOBurnRateCritical
        exp_alerts:
          - exp_labels:
              severity: critical
              service: checkout
            exp_annotations:
              summary: "High error budget burn rate (fast burn) for service checkout"
              runbook_url: "https://wiki/runbooks/slo-burn-rate"
```

```bash
promtool check rules sli_rules.yml slo_alerts.yml  # syntax only — proves nothing about firing
promtool test rules slo_test.yml                   # actually evaluates the alert
```

Run both in CI. Every SLO alert needs at least one unit test that would fail if the
alert stopped firing — that is the only way the "Tested" box below is honest.

## Alert Quality Checklist

Every alert MUST have:
- [ ] **Runbook link** in annotations
- [ ] **Clear summary** describing what is wrong and impact
- [ ] **Severity** matching response expectation (page vs ticket vs log)
- [ ] **Owner** — which team is responsible
- [ ] **Actionable** — recipient can do something about it
- [ ] **Tested** — alert has fired in non-prod and was validated

Alert anti-patterns to avoid:
- Alerting on raw CPU% instead of SLO burn rate
- Flapping alerts (fire and resolve repeatedly)
- Alerts with no runbook ("figure it out yourself")
- Duplicate alerts for the same condition from different sources
- Alerts nobody looks at (alert fatigue → ignored pages)

## Dashboard Design

### Layer 1: Service Overview (start here)

One dashboard per team showing all owned services:
- Traffic (req/sec) per service
- Error rate per service (color: green <0.1%, yellow <1%, red >1%)
- p99 latency per service
- Error budget remaining per service (30-day window)

### Layer 2: Per-Service Deep Dive

- RED metrics broken down by endpoint and status code
- Dependency health (upstream/downstream latencies)
- Recent deployments overlay on graphs
- Top errors table with counts and sample traces

### Layer 3: Infrastructure

- USE metrics per node/pod
- Kubernetes resource utilization vs requests vs limits
- Pod restart counts, eviction counts
- Node health, disk pressure, memory pressure

### Layer 4: Business Metrics

- Conversion rate, cart abandonment, signup completion
- Revenue per minute (correlated with system health)
- Feature flag adoption rates

## OpenTelemetry Instrumentation

### Auto-Instrumentation (Start Here)

```bash
# Node.js — auto-instrument without code changes
npm install @opentelemetry/auto-instrumentations-node
node --require @opentelemetry/auto-instrumentations-node/register app.js

# Python — auto-instrument without code changes
pip install opentelemetry-distro opentelemetry-exporter-otlp
opentelemetry-bootstrap -a install
opentelemetry-instrument python app.py
```

### Manual Spans (Add Business Context)

```typescript
import { trace } from '@opentelemetry/api';

const tracer = trace.getTracer('payment-service');

async function processPayment(order: Order) {
  return tracer.startActiveSpan('process-payment', async (span) => {
    span.setAttribute('order.id', order.id);
    span.setAttribute('order.amount', order.amount);
    span.setAttribute('payment.method', order.paymentMethod);
    try {
      const result = await chargeCard(order);
      span.setAttribute('payment.status', 'success');
      return result;
    } catch (error) {
      span.recordException(error);
      span.setStatus({ code: SpanStatusCode.ERROR });
      throw error;
    } finally {
      span.end();
    }
  });
}
```

### Collector Configuration

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1000
  memory_limiter:
    check_interval: 1s
    limit_mib: 512

exporters:
  prometheus:
    endpoint: 0.0.0.0:8889
  # Loki ingests OTLP natively, so push logs with the core `otlphttp` exporter.
  # It appends the signal path itself: this posts to http://loki:3100/otlp/v1/logs.
  #
  # Do NOT use the old `loki` exporter here. It was deprecated on 2024-07-09 and
  # DELETED from opentelemetry-collector-contrib in v0.131.0 (2025-07-29), and
  # collector config resolution is ALL-OR-NOTHING: one unknown exporter type fails
  # the whole unmarshal at startup — `'exporters' unknown type: "loki" for id:
  # "loki"` — and the process never comes up, so the failure happens before any
  # pipeline is built. A stale logs exporter therefore takes the metrics and
  # traces pipelines down with it — you lose all three signals, not just logs.
  otlphttp/loki:
    endpoint: http://loki:3100/otlp
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/loki]
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/tempo]
```

## Structured Logging

```json
{
  "timestamp": "2026-03-21T10:30:00.000Z",
  "level": "error",
  "service": "payment-api",
  "trace_id": "abc123def456",
  "span_id": "789ghi",
  "message": "Payment processing failed",
  "error.type": "CardDeclinedException",
  "error.message": "Insufficient funds",
  "order.id": "ord-12345",
  "http.method": "POST",
  "http.path": "/api/payments",
  "http.status_code": 402,
  "duration_ms": 234
}
```

Rules:
- Always JSON, never unstructured text in production
- Include trace_id and span_id for correlation
- Use consistent field names (follow OTel semantic conventions)
- Redact PII: credit card numbers, passwords, tokens, email addresses
- Log levels: ERROR (action needed), WARN (degraded), INFO (significant events), DEBUG (dev only, never in prod)

## Cost Management

Observability can become expensive. Control costs with:

- **Sampling**: Use head-based (10% of traces) or tail-based (100% of errors/slow) in OTel Collector
- **Retention**: 15 days for metrics, 7 days for logs, 3 days for traces (adjust per need)
- **Cardinality**: Never use user_id, request_id, or session_id as metric labels
- **Aggregation**: Pre-aggregate in recording rules, query aggregated data
- **Tiering**: Hot (recent, fast queries) → Warm (older, slower) → Cold (archive, S3)
