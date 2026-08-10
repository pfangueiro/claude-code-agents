---
name: ci-cd-templates
description: Production-ready CI/CD pipeline templates for GitHub Actions and GitLab CI
---

# CI/CD Templates Skill

Provides production-ready CI/CD pipeline templates for GitHub Actions and GitLab CI.

## Purpose

This skill provides:
- GitHub Actions workflow templates
- GitLab CI/CD pipeline configurations
- Best practices for automated testing, building, and deployment
- Security scanning integration
- Deployment strategies (blue/green, canary, rolling)

## When to Use

- "Create a CI/CD pipeline for Node.js"
- "Add GitHub Actions for testing and deployment"
- "Set up automated deployments to AWS"
- "Configure GitLab CI for Docker builds"

## GitHub Actions Templates

### Node.js CI/CD Pipeline

```yaml
name: Node.js CI/CD

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

# An unqualified image name (`myapp`) resolves to docker.io/library/myapp —
# the Docker official-images namespace, which you cannot push to. Always
# fully qualify the image with a registry host and an owner/namespace.
# Set DOCKER_REGISTRY (e.g. ghcr.io, docker.io) and DOCKER_NAMESPACE as
# repository variables: Settings > Secrets and variables > Actions > Variables.
env:
  REGISTRY: ${{ vars.DOCKER_REGISTRY }}
  IMAGE_NAME: ${{ vars.DOCKER_REGISTRY }}/${{ vars.DOCKER_NAMESPACE }}/myapp

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [18.x, 20.x]

    steps:
    - uses: actions/checkout@v4

    - name: Use Node.js ${{ matrix.node-version }}
      uses: actions/setup-node@v4
      with:
        node-version: ${{ matrix.node-version }}
        cache: 'npm'

    - name: Install dependencies
      run: npm ci

    - name: Run linter
      run: npm run lint

    - name: Run tests
      run: npm test

    - name: Upload coverage
      uses: codecov/codecov-action@v4
      if: matrix.node-version == '20.x'
      with:
        token: ${{ secrets.CODECOV_TOKEN }}
        # fail_ci_if_error defaults to false: without this, a failed upload
        # is reported as a green step and coverage silently stops arriving.
        fail_ci_if_error: true

  security:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Run Snyk security scan
      # Pinned to a release tag — @master is a mutable ref that silently
      # changes what code runs in your pipeline.
      uses: snyk/actions/node@v1.0.0
      env:
        SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}

    - name: Run npm audit
      run: npm audit --production

  build:
    needs: [test, security]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    steps:
    - uses: actions/checkout@v4

    - name: Build Docker image
      run: docker build -t "$IMAGE_NAME:${{ github.sha }}" .

    - name: Log in to the container registry
      uses: docker/login-action@v3
      with:
        registry: ${{ env.REGISTRY }}
        username: ${{ secrets.DOCKER_USERNAME }}
        password: ${{ secrets.DOCKER_PASSWORD }}

    - name: Push Docker image
      run: |
        docker tag "$IMAGE_NAME:${{ github.sha }}" "$IMAGE_NAME:latest"
        docker push "$IMAGE_NAME:${{ github.sha }}"
        docker push "$IMAGE_NAME:latest"

  deploy:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    steps:
    - name: Deploy to production
      uses: appleboy/ssh-action@v1.0.0
      with:
        host: ${{ secrets.DEPLOY_HOST }}
        username: ${{ secrets.DEPLOY_USER }}
        key: ${{ secrets.DEPLOY_KEY }}
        # Interpolated by the runner: $IMAGE_NAME does not exist on the
        # remote host, so the fully qualified name must be baked in here.
        script: |
          # The registry login in the build job happened on the RUNNER. This
          # script runs on the remote host, which has never authenticated —
          # pulling a private image there fails with 'denied: requested
          # access to the resource is denied'. Log in before pulling.
          echo "${{ secrets.DOCKER_PASSWORD }}" \
            | docker login ${{ env.REGISTRY }} -u "${{ secrets.DOCKER_USERNAME }}" --password-stdin
          docker pull ${{ env.IMAGE_NAME }}:latest
          docker-compose up -d
```

### TypeScript + Vitest Pipeline

```yaml
name: TypeScript CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v4

    - name: Setup Node.js
      uses: actions/setup-node@v4
      with:
        node-version: '20'
        cache: 'npm'

    - run: npm ci

    - name: Type check
      run: npm run type-check

    - name: Run tests with coverage
      run: npm run test:coverage

    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v4
      with:
        # Without this the upload is fail-open — an upload error still
        # reports a green step.
        fail_ci_if_error: true
```

## GitLab CI Templates

### Full-Stack Application Pipeline

```yaml
stages:
  - build
  - test
  - security
  - deploy

variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: "/certs"

build:
  stage: build
  image: node:20-alpine
  script:
    - npm ci
    - npm run build
  artifacts:
    paths:
      - dist/
    expire_in: 1 hour

test:unit:
  stage: test
  image: node:20-alpine
  script:
    - npm ci
    - npm run test:coverage
  coverage: '/All files[^|]*\|[^|]*\s+([\d\.]+)/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage/cobertura-coverage.xml

test:e2e:
  stage: test
  image: mcr.microsoft.com/playwright:v1.40.0
  script:
    - npm ci
    - npx playwright install
    - npm run test:e2e
  artifacts:
    when: on_failure
    paths:
      - playwright-report/

security:sast:
  stage: security
  image: returntocorp/semgrep
  script:
    # --error makes semgrep exit 1 on findings. Without it semgrep exits 0
    # even when it finds something, and the gate can never fail the pipeline.
    # --gitlab-sast emits GitLab's SAST report schema; a raw --json file
    # fails schema validation and is silently not ingested.
    - semgrep --config=auto --error --gitlab-sast --output=gl-sast-report.json .
  artifacts:
    # The gate is supposed to fail, and artifacts:when defaults to on_success,
    # so without this the report is discarded exactly when it matters.
    when: always
    reports:
      sast: gl-sast-report.json

security:dependency:
  stage: security
  image: node:20-alpine
  script:
    # npm audit exits non-zero when vulnerabilities are found, so this gate
    # does fail the pipeline.
    - npm audit --json > npm-audit.json
  artifacts:
    when: always
    # Kept as a plain artifact, NOT declared under `reports:`. Raw npm audit
    # JSON does not conform to GitLab's dependency-scanning report schema, and
    # a report that fails validation is dropped — leaving a dashboard that
    # shows a clean all-clear it never actually verified. Use GitLab's own
    # Dependency-Scanning.gitlab-ci.yml template if you need the report.
    paths:
      - npm-audit.json

deploy:staging:
  stage: deploy
  image: alpine:latest
  before_script:
    - apk add --no-cache curl
  script:
    - curl --fail --show-error --silent -X POST $DEPLOY_WEBHOOK_STAGING
  only:
    - develop

deploy:production:
  stage: deploy
  image: alpine:latest
  before_script:
    - apk add --no-cache curl
  script:
    - curl --fail --show-error --silent -X POST $DEPLOY_WEBHOOK_PRODUCTION
  only:
    - main
  when: manual
```

## Deployment Strategies

### Blue/Green Deployment (AWS)

```yaml
name: Blue/Green Deploy

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Configure AWS credentials
      uses: aws-actions/configure-aws-credentials@v4
      with:
        aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
        aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        aws-region: us-east-1

    - name: Deploy to green environment
      id: deploy
      run: |
        # create-deployment is ASYNC — it returns a deployment ID immediately,
        # long before the revision is live. Capture the ID so the next step
        # can block on it.
        DEPLOYMENT_ID=$(aws deploy create-deployment \
          --application-name my-app \
          --deployment-group-name green-env \
          --s3-location bucket=my-bucket,key=app.zip,bundleType=zip \
          --query deploymentId --output text)
        echo "deployment-id=$DEPLOYMENT_ID" >> "$GITHUB_OUTPUT"

    - name: Wait for the green deployment to succeed
      run: |
        # Without this waiter the smoke tests below hit the PREVIOUS build
        # while the new one is still rolling out: they pass, and a broken
        # revision gets promoted. The waiter exits non-zero on a failed or
        # timed-out deployment, so the job fails closed.
        aws deploy wait deployment-successful \
          --deployment-id ${{ steps.deploy.outputs.deployment-id }}

    - name: Run smoke tests
      run: ./scripts/smoke-test.sh https://green.example.com

    - name: Switch traffic to green
      run: |
        # Every entry in --default-actions requires Type. Omitting it fails
        # client-side with 'Missing required parameter in DefaultActions[0]:
        # "Type"', so the one step that promotes green never runs.
        aws elbv2 modify-listener \
          --listener-arn ${{ secrets.LISTENER_ARN }} \
          --default-actions Type=forward,TargetGroupArn=${{ secrets.GREEN_TARGET_GROUP }}

    - name: Monitor deployment
      run: ./scripts/monitor-metrics.sh
```

### Canary Deployment (Kubernetes)

```yaml
name: Canary Deploy

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Configure AWS credentials
      uses: aws-actions/configure-aws-credentials@v4
      with:
        aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
        aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        aws-region: us-east-1

    - name: Set up kubectl
      uses: azure/setup-kubectl@v3

    - name: Configure kubeconfig
      # setup-kubectl installs the BINARY only — it writes no kubeconfig and
      # authenticates nothing. Without this step every kubectl call below
      # fails because it has no cluster to talk to.
      run: aws eks update-kubeconfig --name ${{ vars.EKS_CLUSTER_NAME }} --region us-east-1

    - name: Deploy canary (10% traffic)
      run: |
        kubectl apply -f k8s/canary-10.yaml
        # Wait on the manifest just applied, never on a hardcoded name. A literal
        # `deployment/app-canary` that does not match this file returns 0 instantly
        # against whatever else is already converged, and the gate passes vacuously.
        # (-f needs the file to hold the rollout-able workload; a mixed file errors
        # loudly, which is the correct direction to fail.)
        kubectl rollout status -f k8s/canary-10.yaml --timeout=10m

    - name: Monitor metrics for 10 minutes
      run: ./scripts/monitor-canary.sh 600

    - name: Increase to 50% traffic
      run: |
        kubectl apply -f k8s/canary-50.yaml
        # apply only records desired state. Without this wait the monitor
        # below measures the still-running 10% pods and reports the 50%
        # step healthy — the same fail-open shape as an unwaited deploy.
        kubectl rollout status -f k8s/canary-50.yaml --timeout=10m

    - name: Monitor metrics for 10 minutes
      run: ./scripts/monitor-canary.sh 600

    - name: Full rollout
      run: |
        kubectl apply -f k8s/production.yaml
        # Production must converge BEFORE the canary is deleted — removing it
        # first drops serving pods while the rollout is still in progress.
        kubectl rollout status -f k8s/production.yaml --timeout=10m
        kubectl delete -f k8s/canary-50.yaml
```

## Best Practices

1. **Always run tests before deployment**
2. **Use matrix builds for multiple environments**
3. **Implement security scanning (SAST, dependency checks)**
4. **Cache dependencies to speed up builds**
5. **Use secrets for sensitive data**
6. **Implement rollback strategies**
7. **Monitor deployments with health checks**
8. **Use environment-specific configurations**

## Integration with Agents

Works best with:
- **devops-automation** agent - Generates pipelines for specific platforms
- **security-auditor** agent - Adds security scanning steps
- **test-automation** agent - Integrates testing frameworks

## References

- [GitHub Actions Documentation](https://docs.github.com/actions)
- [GitLab CI/CD](https://docs.gitlab.com/ee/ci/)
