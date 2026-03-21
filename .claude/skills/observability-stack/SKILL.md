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
    rules:
      # Availability SLI: ratio of successful requests
      - record: sli:availability:ratio_rate5m
        expr: |
          sum(rate(http_requests_total{status!~"5.."}[5m]))
          / sum(rate(http_requests_total[5m]))

      # Latency SLI: ratio of requests faster than 300ms
      - record: sli:latency:ratio_rate5m
        expr: |
          sum(rate(http_request_duration_seconds_bucket{le="0.3"}[5m]))
          / sum(rate(http_request_duration_seconds_count[5m]))
```

### Error Budget Calculation

```promql
# Error budget remaining (30-day window)
1 - (
  (1 - avg_over_time(sli:availability:ratio_rate5m[30d]))
  / (1 - 0.999)  # SLO target
)
```

### Multi-Window Multi-Burn-Rate Alerts

Google SRE recommended approach — alert on budget consumption rate, not raw thresholds.

```yaml
groups:
  - name: slo_alerts
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
          summary: "High error budget burn rate (fast burn)"
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
          summary: "Elevated error budget burn rate (slow burn)"

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
```

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
  loki:
    endpoint: http://loki:3100/loki/api/v1/push
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
      exporters: [loki]
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
