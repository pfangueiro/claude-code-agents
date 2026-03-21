---
name: kubernetes-ops
description: Kubernetes operations, manifest generation, Helm charts, Karpenter autoscaling, GitOps (ArgoCD/Flux), network policies, pod security, and troubleshooting. Auto-activates on Kubernetes, K8s, kubectl, pod, deployment, service, ingress, helm, karpenter, eks, gke, aks, node, cluster, namespace, HPA, autoscaling.
---

# Kubernetes Operations

## Overview

Production-ready Kubernetes patterns with security-hardened defaults. Covers manifest generation, autoscaling, GitOps, networking, and troubleshooting.

## Manifest Templates

### Deployment (Security-Hardened)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: APP_NAME
  labels:
    app.kubernetes.io/name: APP_NAME
    app.kubernetes.io/version: "1.0.0"
    app.kubernetes.io/managed-by: helm
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: APP_NAME
  template:
    metadata:
      labels:
        app.kubernetes.io/name: APP_NAME
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      serviceAccountName: APP_NAME
      containers:
        - name: APP_NAME
          image: REGISTRY/APP_NAME:TAG
          ports:
            - containerPort: 8080
              protocol: TCP
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 10
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: APP_NAME
```

### PodDisruptionBudget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: APP_NAME
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: APP_NAME
```

### NetworkPolicy (Default Deny + Allow Specific)

```yaml
# Default deny all ingress in namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
spec:
  podSelector: {}
  policyTypes:
    - Ingress
---
# Allow specific traffic
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-APP_NAME
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: APP_NAME
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: frontend
      ports:
        - port: 8080
          protocol: TCP
```

### HorizontalPodAutoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: APP_NAME
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: APP_NAME
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
```

## Karpenter (AWS Node Autoscaling)

Karpenter replaces Cluster Autoscaler with workload-aware, faster node provisioning.

### NodePool

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default
spec:
  template:
    metadata:
      labels:
        managed-by: karpenter
    spec:
      requirements:
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand", "spot"]
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["c", "m", "r"]
        - key: karpenter.k8s.aws/instance-generation
          operator: Gt
          values: ["5"]
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      expireAfter: 720h
  limits:
    cpu: "100"
    memory: 400Gi
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
```

### EC2NodeClass

```yaml
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  amiSelectorTerms:
    - alias: al2023@latest
  role: KarpenterNodeRole-CLUSTER_NAME
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: CLUSTER_NAME
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: CLUSTER_NAME
  blockDeviceMappings:
    - deviceName: /dev/xvda
      ebs:
        volumeSize: 50Gi
        volumeType: gp3
        encrypted: true
```

### Autoscaling Tiers

| Tier | Tool | What It Scales | When to Use |
|------|------|---------------|-------------|
| 1 | HPA | Pod replicas | CPU/memory-based, always start here |
| 2 | VPA | Pod resource requests | Right-sizing, don't combine with HPA on same metric |
| 3 | Karpenter | Nodes | Workload-aware node provisioning, replaces Cluster Autoscaler |
| 4 | KEDA | Pod replicas | Event-driven (queue depth, Kafka lag, custom metrics) |

## GitOps Patterns

### ArgoCD Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: APP_NAME
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/ORG/REPO.git
    targetRevision: main
    path: k8s/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: APP_NAME
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
    retry:
      limit: 3
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

### Flux Kustomization

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: APP_NAME
  namespace: flux-system
spec:
  interval: 5m
  path: ./k8s/overlays/production
  prune: true
  sourceRef:
    kind: GitRepository
    name: APP_NAME
  healthChecks:
    - apiVersion: apps/v1
      kind: Deployment
      name: APP_NAME
      namespace: APP_NAME
```

## Helm Chart Scaffold

```
mychart/
├── Chart.yaml
├── values.yaml
├── values-dev.yaml
├── values-staging.yaml
├── values-prod.yaml
├── templates/
│   ├── _helpers.tpl
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── hpa.yaml
│   ├── pdb.yaml
│   ├── networkpolicy.yaml
│   ├── serviceaccount.yaml
│   └── configmap.yaml
└── .helmignore
```

Always: pin chart versions, validate with `helm lint` and `helm template` in CI, use values files per environment.

## Troubleshooting Decision Trees

### Pod Not Starting

```
Pod status?
├── Pending
│   ├── Check events: kubectl describe pod POD
│   ├── "Insufficient cpu/memory" → check resource requests, node capacity
│   ├── "no nodes match" → check nodeSelector, tolerations, affinity
│   └── "PVC not bound" → check storage class, PV availability
├── CrashLoopBackOff
│   ├── Check logs: kubectl logs POD --previous
│   ├── OOMKilled → increase memory limits
│   ├── Application error → fix code, check config
│   └── Readiness probe failing → check probe config, startup time
├── ImagePullBackOff
│   ├── Check image name and tag exist
│   ├── Check imagePullSecrets for private registries
│   └── Check network access to registry
└── Error / Unknown
    ├── Check events: kubectl describe pod POD
    └── Check node status: kubectl get nodes
```

### Service Not Reachable

```
1. Verify pod is Running: kubectl get pods -l app=APP_NAME
2. Verify service exists: kubectl get svc APP_NAME
3. Check endpoints: kubectl get endpoints APP_NAME
   └── Empty? Labels don't match between Service and Pod selectors
4. Test from within cluster: kubectl run debug --rm -it --image=busybox -- wget -qO- http://APP_NAME:PORT
5. Check network policies: kubectl get networkpolicy -n NAMESPACE
6. Check ingress/load balancer: kubectl describe ingress APP_NAME
```

## Security Checklist

- [ ] Pods run as non-root (`runAsNonRoot: true`)
- [ ] Read-only root filesystem (`readOnlyRootFilesystem: true`)
- [ ] All capabilities dropped (`drop: ["ALL"]`)
- [ ] No privilege escalation (`allowPrivilegeEscalation: false`)
- [ ] Seccomp profile set (`seccompProfile: RuntimeDefault`)
- [ ] Resource requests AND limits set on every container
- [ ] NetworkPolicies enforce least-privilege network access
- [ ] PodDisruptionBudgets protect availability during disruptions
- [ ] ServiceAccounts use least-privilege RBAC
- [ ] Images from trusted registries only, scanned with Trivy
- [ ] Secrets mounted as volumes, not environment variables
- [ ] No `latest` image tag — use immutable digests or semantic versions
