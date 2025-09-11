# Claude Code Agents v3.0

A collection of specialized AI agents for Claude Code with automatic activation, intelligent coordination, and cost optimization.

## Quick Setup

```bash
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash -s /path/to/project
```

Or clone manually:
```bash
git clone https://github.com/pfangueiro/claude-code-agents.git
cd claude-code-agents
./install.sh /path/to/your/project
```

## What You Get

### 23 Specialized Agents
- **Development**: api-builder, frontend-architect, database-architect, mobile-developer
- **Languages**: python-expert, typescript-expert, infrastructure-expert
- **Quality**: test-engineer, secure-coder, performance-optimizer, refactor-specialist  
- **DevOps**: deployment-engineer, pwa-architect
- **Design**: ui-ux-specialist, documentation-specialist
- **Management**: project-coordinator, directory-scanner, meta-agent
- **Intelligence**: context-analyzer, ai-optimizer, integration-specialist, workflow-learner, health-monitor

### Auto-Activation
Agents activate automatically when you mention relevant keywords:
- "Create a REST API" → api-builder + secure-coder activate
- "Optimize database queries" → database-architect + performance-optimizer activate
- "Build React component" → frontend-architect + typescript-expert activate

### Cost Optimization
- Smart model selection (Haiku $0.80/1M, Sonnet $3/1M, Opus $15/1M tokens)
- Automatic cost tracking and optimization
- 60%+ cost reduction through intelligent model assignment

### Quality Gates
Mandatory validation before deployment:
- test-engineer: All tests must pass
- secure-coder: Security review required
- performance-optimizer: Performance validation

## Usage

After installation, agents work automatically:

```bash
cd your-project
claude
"I need to create user authentication"
# Agents coordinate automatically - no manual setup needed
```

## Commands

Basic commands:
- `/workflow feature` - Run feature development pipeline
- `/quality-check` - Run security, performance, and quality validation
- `/track status` - View agent activity and costs

Advanced commands (v3.0):
- `/auto-optimize` - AI-powered system optimization
- `/health check` - System health and diagnostics
- `/scale up` - Dynamic agent scaling

## Project Types Supported

The installer auto-detects and configures for:
- **Next.js/React**: Frontend-focused agent priorities
- **Python APIs**: Backend and database optimization
- **Node.js**: Full-stack development support
- **Mobile**: React Native/Flutter optimization
- **Infrastructure**: DevOps and deployment focus
- **Generic**: Adaptive configuration for any project

## Configuration

The system generates a project-specific `CLAUDE.md` with:
- Agent priorities for your tech stack
- Workflow patterns optimized for your project type
- Cost optimization settings
- Auto-activation examples

## Monitoring

Built-in tracking system:
- Token usage and cost tracking
- Agent performance metrics
- Success/failure rates
- GitHub integration (optional)

View dashboard: `.claude/scripts/dashboard.sh`

## Requirements

**Required**: git, bash 4.0+
**Recommended**: jq (JSON processing), bc (cost calculations)
**Optional**: gh CLI (GitHub integration)

## Documentation

- `INTEGRATION_GUIDE.md` - Detailed deployment and validation procedures
- `REQUIREMENTS.md` - Complete dependency information
- `TEST_SCENARIOS.md` - Validation and testing guide

## Architecture

### Agent Coordination
- **Sequential**: Agent A → Agent B → Agent C
- **Parallel**: Multiple agents working simultaneously
- **Quality Gates**: Validation checkpoints before deployment

### Storage
- CSV files for metrics and cost tracking
- JSONL files for structured logging
- Daily partitioned data for performance

### External Integrations
- GitHub (repository management)
- Playwright (browser testing)
- Context7 (documentation lookup)
- Magic (UI component generation)

## Contributing

1. Use the meta-agent to create new specialized agents
2. Follow existing agent patterns (YAML frontmatter + markdown)
3. Test agent activation and coordination
4. Submit PR with documentation

## License

MIT License - see LICENSE file for details.

---

**Note**: This system enhances Claude Code with specialized agents. It requires Claude Code to be installed and configured separately.