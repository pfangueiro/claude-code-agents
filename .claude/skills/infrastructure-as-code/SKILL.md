---
name: infrastructure-as-code
description: Infrastructure as Code decision framework, testing pyramid, CI/CD for infrastructure, state management, module composition, policy-as-code, and drift detection. Covers Terraform, CloudFormation, CDK, Pulumi patterns. Auto-activates on Terraform, CloudFormation, CDK, Pulumi, infrastructure as code, IaC, module, state, tfstate, HCL, stack, drift.
---

# Infrastructure as Code

## Overview

Tool-agnostic IaC best practices covering the decision framework, testing pyramid, CI/CD integration, state management, and policy enforcement. Includes Terraform-focused examples as the most common tool.

## Tool Selection Decision Matrix

| Factor | Terraform | CloudFormation | CDK | Pulumi |
|--------|-----------|---------------|-----|--------|
| **Multi-cloud** | Excellent | AWS only | AWS (multi via constructs) | Excellent |
| **Language** | HCL | JSON/YAML | TypeScript/Python/Java | TypeScript/Python/Go |
| **State** | External (S3, etc.) | AWS-managed | AWS-managed | Pulumi Cloud or self-hosted |
| **Ecosystem** | Largest provider registry | AWS-native | Growing | Growing |
| **Learning curve** | Moderate (HCL) | Low (declarative) | Low (familiar lang) | Low (familiar lang) |
| **Testing** | Native tests + Terratest | TaskCat, cfn-lint | CDK assertions | Pulumi testing |
| **Best for** | Multi-cloud, large teams | AWS-only shops | AWS devs who prefer code | Devs who dislike DSLs |

**Recommendation**: Default to Terraform for multi-cloud or large teams. Use CDK/Pulumi if team strongly prefers general-purpose languages. Use CloudFormation if AWS-only and team already knows it.

## Project Structure

### Terraform Layout

```
infrastructure/
├── modules/                    # Reusable modules
│   ├── vpc/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── README.md
│   ├── eks/
│   ├── rds/
│   └── lambda/
├── environments/               # Per-environment configs
│   ├── dev/
│   │   ├── main.tf            # Module composition
│   │   ├── variables.tf
│   │   ├── terraform.tfvars
│   │   ├── backend.tf         # S3 + DynamoDB state config
│   │   └── providers.tf
│   ├── staging/
│   └── prod/
├── policies/                   # OPA/Sentinel policies
│   └── deny-public-s3.rego
└── tests/                      # Integration tests
    └── vpc_test.go
```

**Key rules:**
- Separate state per environment (separate backend.tf)
- Shared modules in `modules/`, consumed by `environments/`
- Pin module versions: `source = "../modules/vpc"` or `version = "~> 2.0"`
- Pin provider versions in `providers.tf`
- Never commit `.tfstate` or `.tfvars` with secrets

### Module Design

```hcl
# modules/vpc/variables.tf
variable "name" {
  description = "VPC name"
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.name))
    error_message = "Name must be lowercase alphanumeric with hyphens."
  }
}

variable "cidr_block" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"

  validation {
    condition     = can(cidrhost(var.cidr_block, 0))
    error_message = "Must be a valid CIDR block."
  }
}

variable "availability_zones" {
  description = "List of AZs to use"
  type        = list(string)
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
```

**Module rules:**
- One concern per module (VPC, EKS, RDS — not "everything")
- All inputs as variables with descriptions, types, and validations
- All outputs documented
- Use `for_each` over `count` for stable resource identity
- Use `locals` for computed values
- Generate docs with `terraform-docs`
- Semantic versioning when publishing

## IaC Testing Pyramid

Run in order, fail fast:

### Layer 1: Format & Validate (seconds)

```bash
# Pre-commit hook or CI step 1
terraform fmt -check -recursive
terraform validate
```

### Layer 2: Lint (seconds)

```bash
# Enforce best practices
tflint --recursive
# Check for deprecated syntax, naming conventions, unused variables
```

### Layer 3: Security Scan (seconds)

```bash
# Detect misconfigurations
checkov -d .
# or
tfsec .
# Catches: public S3 buckets, open security groups, unencrypted resources, missing tags
```

### Layer 4: Plan & Cost (minutes)

```bash
# Preview changes — mandatory before apply
terraform plan -out=tfplan

# Estimate cost impact (Infracost)
infracost breakdown --path=tfplan --format=json
# Post cost diff as PR comment
infracost diff --path=tfplan --compare-to=infracost-base.json
```

### Layer 5: Policy-as-Code (seconds)

```bash
# OPA (Open Policy Agent) — custom guardrails
terraform show -json tfplan > tfplan.json

# Preflight: parse-check the policies FIRST. `opa check` exits 1 on a syntax
# error, so a broken policy is caught here instead of silently never running.
opa check policies/

# -i/--input takes a FILE PATH, not stdin (use --stdin-input to pipe instead).
# --fail-defined exits 1 when the query is defined, i.e. when deny has entries;
# index with [_] so the query stays undefined (exit 0) when there are none —
# a bare 'data.terraform.deny' is an empty set, which is always defined (exit 1).
opa eval -d policies/ -i tfplan.json --fail-defined --format pretty 'data.terraform.deny[_]'; rc=$?

# Exit contract — FAIL CLOSED. Measured on OPA 1.19.0:
#   0 = no violations   1 = violations   2 = error (parse failure, missing input/policy dir)
# Never key the gate on `-eq 1` alone: exit 2 means the policy never evaluated,
# and reading that as "clean" lets an unparseable policy wave every change through.
case $rc in
  0) echo "policy: clean" ;;
  1) echo "policy: violations"; exit 1 ;;
  *) echo "policy: ERROR — did not evaluate"; exit 1 ;;
esac

# Example policy: deny public S3 buckets
# policies/deny-public-s3.rego
# Rego v1: OPA 1.0+ requires `contains` for partial set rules and `if` before the
# body. `import rego.v1` is a no-op on 1.x and keeps the file valid on 0.59+.
package terraform
import rego.v1

deny contains msg if {
  resource := input.resource_changes[_]
  resource.type == "aws_s3_bucket"
  resource.change.after.acl == "public-read"
  msg := sprintf("S3 bucket %s must not be public", [resource.address])
}
```

### Layer 6: Integration Tests (minutes)

```go
// tests/vpc_test.go (Terratest)
func TestVPCCreation(t *testing.T) {
    terraformOptions := &terraform.Options{
        TerraformDir: "../modules/vpc",
        Vars: map[string]interface{}{
            "name":               "test-vpc",
            "cidr_block":         "10.0.0.0/16",
            "availability_zones": []string{"us-east-1a", "us-east-1b"},
        },
    }
    defer terraform.Destroy(t, terraformOptions)
    terraform.InitAndApply(t, terraformOptions)

    vpcID := terraform.Output(t, terraformOptions, "vpc_id")
    assert.NotEmpty(t, vpcID)
}
```

Or use native Terraform tests (1.6+):

```hcl
# tests/vpc.tftest.hcl
run "create_vpc" {
  command = apply

  variables {
    name               = "test-vpc"
    cidr_block         = "10.0.0.0/16"
    availability_zones = ["us-east-1a", "us-east-1b"]
  }

  assert {
    condition     = output.vpc_id != ""
    error_message = "VPC ID must not be empty"
  }
}
```

## CI/CD for Infrastructure

### GitHub Actions Workflow

```yaml
name: Infrastructure
on:
  pull_request:
    paths: ['infrastructure/**']
  push:
    branches: [main]
    paths: ['infrastructure/**']

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3

      - name: Format Check
        run: terraform fmt -check -recursive
        working-directory: infrastructure

      - name: Validate
        run: |
          for env in infrastructure/environments/*/; do
            terraform -chdir="$env" init -backend=false
            terraform -chdir="$env" validate
          done

      - name: Lint
        run: tflint --recursive
        working-directory: infrastructure

      - name: Security Scan
        run: checkov -d infrastructure/ --quiet

  plan:
    needs: validate
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    environment: plan
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3

      - name: Plan
        run: |
          terraform -chdir=infrastructure/environments/prod init
          terraform -chdir=infrastructure/environments/prod plan -out=tfplan -no-color
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}

      - name: Cost Estimate
        uses: infracost/actions/setup@v3
      - run: infracost diff --path=infrastructure/environments/prod/tfplan --format=json --out-file=/tmp/infracost.json
      - uses: infracost/actions/comment@v3
        with:
          path: /tmp/infracost.json
          behavior: update

  apply:
    # Depends on validate, NOT plan: plan is pull_request-only, and a skipped
    # dependency skips its dependents — needs:plan would make apply unreachable.
    needs: validate
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: production  # Requires manual approval
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3

      # Apply a PLAN, never a bare `apply -auto-approve`: with no plan file Terraform
      # re-resolves state at apply time, so what executes is not what anyone reviewed —
      # the PR plan above is advisory only. Planning and applying in the SAME job at least
      # makes the applied plan the one printed in this log. Stronger: upload the plan as an
      # artifact keyed by commit SHA and download it here instead of re-planning.
      - name: Plan and apply
        run: |
          terraform -chdir=infrastructure/environments/prod init
          terraform -chdir=infrastructure/environments/prod plan -out=tfplan
          terraform -chdir=infrastructure/environments/prod apply tfplan
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

### GitOps Flow

```
Developer → PR with infra changes
  → CI: fmt + validate + lint + security scan (automated)
  → CI: terraform plan + cost estimate (automated, posted as PR comment)
  → Review: team reviews plan output and cost impact
  → Approve: merge to main
  → CD: terraform apply (automated with manual approval gate for prod)
```

**Rules:**
- Never `terraform apply` from local machines in production
- Plan output must be reviewed by a human before apply
- Production apply requires explicit approval (GitHub environment protection)
- All state operations logged for audit

## State Management

### Remote State (Terraform + AWS)

```hcl
# backend.tf
terraform {
  backend "s3" {
    bucket         = "mycompany-terraform-state"
    key            = "prod/vpc/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-locks"
    encrypt        = true
  }
}
```

**State rules:**
- Always use remote backend (never local state in production)
- Enable encryption at rest
- Enable state locking (DynamoDB for AWS, GCS for GCP)
- Enable versioning on state bucket (disaster recovery)
- Separate state per component AND per environment
- State key pattern: `<env>/<component>/terraform.tfstate`
- Never store state in Git
- Use `terraform state mv` for refactoring, with backup

### Drift Detection

```bash
# Schedule in CI (weekly or daily)
terraform plan -detailed-exitcode
rc=$?
case $rc in
  0) echo "no drift" ;;
  2) echo "DRIFT: changes detected — investigate manual changes"; exit 1 ;;
  *) echo "BROKEN: drift check did not run (exit $rc)"; exit 1 ;;
esac
```

**Alert on exit 1 as loudly as on exit 2.** Alerting only on `2` is a fail-open: this job is
scheduled and unattended, so expired credentials, an unreachable backend or a syntax error exit `1`
and produce **silence** — which is indistinguishable from "no drift" to everyone watching. The
failure mode is a drift detector that has quietly not run for weeks. Never let "did not run" share
an outcome with "nothing to report".

## Common AWS Patterns

### VPC with Public/Private Subnets

```hcl
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.project}-${var.environment}"
  cidr = var.vpc_cidr

  azs             = var.availability_zones
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  enable_nat_gateway   = true
  single_nat_gateway   = var.environment != "prod"  # Cost: single for dev, per-AZ for prod
  enable_dns_hostnames = true

  tags = merge(var.tags, {
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  })

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"           = 1
    "karpenter.sh/discovery"                    = var.cluster_name
  }

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
}
```

### Tagging Strategy

```hcl
# providers.tf — apply default tags to ALL resources
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Environment = var.environment
      Project     = var.project
      ManagedBy   = "terraform"
      Team        = var.team
      CostCenter  = var.cost_center
    }
  }
}
```

**Required tags** (enforce via OPA/Config Rules):
- `Environment`: dev/staging/prod
- `Project`: application name
- `ManagedBy`: terraform/manual/cdk
- `Team`: owning team
- `CostCenter`: billing allocation

## Anti-Patterns

- Monolithic state file for entire infrastructure (one blast radius)
- `terraform apply` from laptops (no audit trail, no review)
- No state locking (corruption from concurrent runs)
- Hardcoded values (regions, account IDs, CIDRs)
- No security scanning in pipeline
- Using `count` for resources with side effects on index changes
- `terraform destroy` without confirming scope
- Committing `.tfvars` with secrets
- No drift detection (manual changes go unnoticed)
- Skipping `terraform plan` review before apply

## References

- Anton Babenko's terraform-skill: comprehensive Terraform-specific patterns
- HashiCorp official agent skills: Terraform and Packer best practices
- Pulumi agent skills: Pulumi-specific patterns and migration guides
