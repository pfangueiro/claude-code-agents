# Branching Models — Detailed Comparison

Choosing the right branching strategy depends on team size, release cadence, and deployment maturity.

---

## Git Flow

**Best for:** Teams with scheduled releases, multiple supported versions, enterprise software.

```
main ──────●──────────────────●──────────── (releases)
            \                /
develop ─────●──●──●──●──●──● ──────────── (integration)
              \   /     \   /
feature/A ─────●──●      \ /
                   feature/B ──●──●
```

### Branches
| Branch | Purpose | Lifetime |
|--------|---------|----------|
| `main` | Production releases only | Permanent |
| `develop` | Integration of completed features | Permanent |
| `feature/*` | New features | Days to weeks |
| `release/*` | Release stabilization | Days |
| `hotfix/*` | Emergency production fixes | Hours to days |

### Pros
- Clear separation between development and production
- Supports multiple release versions simultaneously
- Well-defined process for hotfixes
- Works well with scheduled release cycles

### Cons
- Complex — many branch types to manage
- Slow for continuous deployment
- Merge conflicts accumulate on develop
- Overhead for small teams

---

## GitHub Flow

**Best for:** Teams practicing continuous deployment, web applications, SaaS products.

```
main ──●──●──●──●──●──●──●──●── (always deployable)
        \       /   \     /
feature/A ──●──●     \   /
                  feature/B ──●
```

### Branches
| Branch | Purpose | Lifetime |
|--------|---------|----------|
| `main` | Always deployable, production code | Permanent |
| `feature/*` | All work (features, fixes, experiments) | Hours to days |

### Process
1. Branch from `main`
2. Make changes, commit, push
3. Open pull request
4. Review, discuss, iterate
5. Deploy from feature branch (or after merge)
6. Merge to `main`

### Pros
- Simple — only two branch types
- Fast iteration cycle
- Encourages small, frequent merges
- Natural fit for CI/CD

### Cons
- No staging/integration branch
- Requires mature CI/CD and automated testing
- Harder to manage multiple release versions
- Feature flags needed for incomplete features

---

## Trunk-Based Development

**Best for:** High-performing teams with excellent CI/CD, mature testing practices.

```
main ──●──●──●──●──●──●──●──●──●── (all work here)
        \   /
short-lived ──● (optional, < 1 day)
```

### Branches
| Branch | Purpose | Lifetime |
|--------|---------|----------|
| `main` (trunk) | All development happens here | Permanent |
| Short-lived branches | Optional, for code review | Hours (< 1 day) |

### Key Practices
- Commit directly to main (or via very short-lived branches)
- Feature flags for incomplete features
- Comprehensive automated test suite is mandatory
- Continuous integration runs on every commit
- Release from main using tags or release branches cut at release time

### Pros
- Fastest feedback loop
- Minimal merge conflicts
- Encourages small, incremental changes
- Simplest branch model

### Cons
- Requires excellent automated testing
- Feature flags add complexity
- Not suitable for teams without CI/CD maturity
- Risky without strong code review culture

---

## Choosing a Model

```
What is your release cadence?
├── Scheduled releases (monthly, quarterly)
│   └── Multiple supported versions?
│       ├── YES → Git Flow
│       └── NO → GitHub Flow with release tags
├── Continuous deployment (daily/weekly)
│   └── Team CI/CD maturity?
│       ├── HIGH → Trunk-Based Development
│       └── MODERATE → GitHub Flow
└── Ad-hoc releases
    └── GitHub Flow
```

### Migration Path
Most teams evolve through these models as they mature:

```
Git Flow → GitHub Flow → Trunk-Based Development
(more process)           (less process, more automation)
```

---

## Hybrid Approaches

### GitHub Flow + Release Branches
- Use GitHub Flow for daily development
- Cut release branches when stabilizing for a release
- Useful for mobile apps or software with a review/approval process

### Trunk-Based + Short-Lived Feature Branches
- Default to working on main
- Use feature branches only when code review is needed
- Branch lifetime strictly < 1 day
- Most common in high-performing teams
