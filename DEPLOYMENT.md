# Deployment Guide - Claude Agents

**Every scenario. One simple process.**

## 🚀 Scenario 1: Personal New Project

```bash
# Create project
mkdir my-awesome-app
cd my-awesome-app

# Install agents (10 seconds)
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash

# Start building
claude> "Create a web app with user authentication"
```

**Result**: Full project scaffolding with auth system

## 🏢 Scenario 2: Existing Company Project

```bash
# Go to your project
cd company-project

# Install agents
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash

# System auto-detects your stack and optimizes

# Start using immediately
claude> "Add rate limiting to our API endpoints"
```

**Result**: Agents understand your existing code and integrate seamlessly

## 👥 Scenario 3: Team Collaboration

```bash
# One person installs
./install.sh

# Commit to git
git add README.md QUICKSTART.md install.sh .claude/
git commit -m "Add AI coding agents"
git push

# Team members pull
git pull

# Everyone has same agents
claude> "Review the authentication flow"
```

**Result**: Entire team has consistent AI assistance

## 🔄 Scenario 4: CI/CD Pipeline

### GitHub Actions
```yaml
name: AI-Assisted CI/CD

on: [push, pull_request]

jobs:
  ai-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Security Check
        run: |
          chmod +x .claude/router.sh
          .claude/router.sh "Check for security vulnerabilities"

      - name: Test Coverage
        run: |
          .claude/router.sh "Ensure test coverage above 80%"

      - name: Performance Check
        run: |
          .claude/router.sh "Check for performance issues"

      - name: Deploy if Safe
        if: github.ref == 'refs/heads/main'
        run: |
          .claude/router.sh "Deploy to production if all checks pass"
```

### GitLab CI
```yaml
stages:
  - test
  - security
  - deploy

ai-test:
  stage: test
  script:
    - .claude/router.sh "Run all tests and report coverage"

ai-security:
  stage: security
  script:
    - .claude/router.sh "Audit code for vulnerabilities"

ai-deploy:
  stage: deploy
  only:
    - main
  script:
    - .claude/router.sh "Deploy to production environment"
```

## ☁️ Scenario 5: Cloud Environments

### Vercel
```json
// vercel.json
{
  "buildCommand": ".claude/router.sh 'Build for production'",
  "installCommand": "./install.sh"
}
```

### Netlify
```toml
# netlify.toml
[build]
  command = ".claude/router.sh 'Build static site'"

[build.environment]
  NODE_VERSION = "18"
```

### Heroku
```json
// app.json
{
  "scripts": {
    "postdeploy": ".claude/router.sh 'Run post-deployment checks'"
  }
}
```

### AWS
```bash
# buildspec.yml for CodeBuild
version: 0.2

phases:
  install:
    commands:
      - ./install.sh
  pre_build:
    commands:
      - .claude/router.sh "Prepare for AWS deployment"
  build:
    commands:
      - .claude/router.sh "Build and package application"
  post_build:
    commands:
      - .claude/router.sh "Deploy to S3 and CloudFront"
```

## 🐳 Scenario 6: Docker

```dockerfile
FROM node:18-alpine

WORKDIR /app

# Copy agent system
COPY .claude/ .claude/
COPY install.sh .

# Make executable
RUN chmod +x install.sh .claude/router.sh

# Install agents
RUN ./install.sh

# Copy application
COPY . .

# Use agents during build
RUN .claude/router.sh "Optimize build for production"

# Build application
RUN .claude/router.sh "Build application"

EXPOSE 3000

# Health check using agents
HEALTHCHECK CMD .claude/router.sh "Check application health"

CMD ["npm", "start"]
```

## 💻 Scenario 7: Development Environments

### VS Code Devcontainer
```json
// .devcontainer/devcontainer.json
{
  "name": "Project with AI Agents",
  "postCreateCommand": "./install.sh",
  "customizations": {
    "vscode": {
      "settings": {
        "terminal.integrated.defaultProfile.linux": "bash"
      }
    }
  }
}
```

### GitHub Codespaces
```yaml
# .devcontainer/devcontainer.json
{
  "postCreateCommand": "curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash",
  "features": {
    "ghcr.io/devcontainers/features/git:1": {}
  }
}
```

### Replit
```toml
# .replit
run = ".claude/router.sh 'Start development server'"

[nix]
channel = "stable-21_11"

[env]
AGENTS_INSTALLED = "true"
```

## 🏗️ Scenario 8: Microservices

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: ./api
    command: sh -c "./install.sh && .claude/router.sh 'Start API service'"

  frontend:
    build: ./frontend
    command: sh -c "./install.sh && .claude/router.sh 'Start frontend service'"

  worker:
    build: ./worker
    command: sh -c "./install.sh && .claude/router.sh 'Start background worker'"
```

## 📱 Scenario 9: Mobile Development

```bash
# React Native
npx react-native init MyApp
cd MyApp
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
claude> "Add push notifications for iOS and Android"

# Flutter
flutter create my_app
cd my_app
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
claude> "Create a cross-platform authentication flow"
```

## 🔐 Scenario 10: Enterprise Deployment

### Centralized MCP Server
```bash
# On central server
git clone https://github.com/pfangueiro/claude-code-agents
cd claude-code-agents
./install.sh

# Create MCP server config
cat > mcp-config.json << EOF
{
  "agents": {
    "architect": { "model": "sonnet", "access": "all" },
    "guardian": { "model": "sonnet", "access": "all" },
    "connector": { "model": "haiku", "access": "restricted" },
    "documenter": { "model": "haiku", "access": "all" }
  },
  "teams": {
    "frontend": ["architect", "guardian", "documenter"],
    "backend": ["architect", "guardian", "connector"],
    "devops": ["connector", "guardian"]
  }
}
EOF

# Start MCP server
mcp-server start --config mcp-config.json
```

### Client Setup
```bash
# On developer machines
mcp-client connect company-server.internal:8080
claude> "Create service following company standards"
```

## 🎯 Quick Deploy Decision Tree

```
Is this a new project?
  YES → curl install | bash
  NO → Continue

Is this for a team?
  YES → Install + commit to git
  NO → Continue

Need CI/CD?
  YES → Add to GitHub Actions/GitLab CI
  NO → Continue

Using Docker?
  YES → Add to Dockerfile
  NO → Continue

Enterprise scale?
  YES → Deploy as MCP server
  NO → Just use local installation
```

## ⚡ Performance Tips

1. **Cache Installation**: Include agents in Docker image
2. **Parallel Execution**: Run multiple requests simultaneously
3. **History Optimization**: Clean history weekly
4. **Network**: Clone repo locally for faster access

## 🛠️ Troubleshooting Deployments

| Issue | Solution |
|-------|----------|
| Agents not found | Run `./install.sh` again |
| Permission denied | `chmod +x install.sh .claude/router.sh` |
| Slow in Docker | Add agents to image, don't install at runtime |
| Team inconsistency | Ensure everyone pulls latest from git |
| CI/CD fails | Check that router.sh is executable |

## 📊 Deployment Metrics

Track deployment success:
```bash
# Add to your monitoring
.claude/router.sh status > /metrics/agents-status.txt
.claude/router.sh history | wc -l > /metrics/agents-usage.txt
```

## 🔄 Updates

```bash
# Get latest version
git pull origin main
./install.sh

# Or re-download
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
```

## ✅ Deployment Checklist

- [ ] Run install.sh
- [ ] Test with simple command
- [ ] Commit to version control (optional)
- [ ] Configure CI/CD (optional)
- [ ] Set up monitoring (optional)

## Remember

**Deployment = Copy + Run**

That's it. No complex configuration, no dependencies, no frameworks.

Just copy `.claude/` folder and run.

---

**Issues?** The system is self-contained. If router.sh exists and is executable, it works.