# Claude Code Agents Collection

A curated collection of 15 specialized AI agents for Claude Code, designed to enhance your development workflow with intelligent, automated assistance.

## 🚀 Overview

This repository contains custom sub-agents that extend Claude Code's capabilities across various development domains. Each agent is optimized with specific tools and activation keywords to provide focused, expert assistance when you need it most.

## 🎯 Key Features

- **Automatic Activation**: Agents activate based on keywords in your requests
- **Specialized Expertise**: Each agent focuses on a specific development domain
- **MCP Server Integration**: Leverages GitHub, Playwright, and other MCP servers
- **Best Practices**: Follows Anthropic's official sub-agent guidelines
- **Proactive Assistance**: Many agents activate automatically during relevant workflows

## 📦 Available Agents

### Development & Architecture

#### 🔧 **api-builder**
- **Activates on**: REST API, GraphQL, API endpoint, web service, HTTP routes, OpenAPI, Swagger
- **Specializes in**: Designing and implementing scalable APIs
- **Key tools**: GitHub integration, documentation lookup

#### 🗄️ **database-architect**
- **Activates on**: database, schema, SQL, NoSQL, MongoDB, PostgreSQL, migrations, indexes
- **Specializes in**: Database design and optimization
- **Key tools**: SQL execution, documentation lookup

#### 🎨 **frontend-architect**
- **Activates on**: frontend, React, Vue, Angular, Svelte, state management, Redux, CSS
- **Specializes in**: Frontend architecture and component design
- **Key tools**: UI component generation (magic), browser testing, framework docs

#### 📱 **mobile-developer**
- **Activates on**: React Native, Flutter, Expo, mobile app, iOS, Android, touch gestures
- **Specializes in**: Mobile app development and optimization
- **Key tools**: Mobile testing, framework documentation

### Code Quality & Testing

#### 🧪 **test-engineer**
- **Activates on**: unit test, integration test, e2e test, Jest, Mocha, Cypress, Playwright
- **Specializes in**: Comprehensive testing strategies
- **Key tools**: Playwright for E2E testing, test framework docs
- **Note**: Activates PROACTIVELY after code changes

#### 🔨 **refactor-specialist**
- **Activates on**: refactor, code smell, technical debt, clean code, SOLID principles
- **Specializes in**: Code improvement and maintainability
- **Note**: Activates PROACTIVELY after feature completion

#### ⚡ **performance-optimizer**
- **Activates on**: performance optimization, slow code, bottleneck, memory leak, caching
- **Specializes in**: Performance analysis and optimization
- **Note**: Activates PROACTIVELY after code changes

#### 🔒 **secure-coder**
- **Activates on**: security, OWASP, authentication, encryption, input validation, XSS
- **Specializes in**: Secure coding practices and implementation
- **Key tools**: Security scanning via GitHub

### DevOps & Infrastructure

#### 🚢 **deployment-engineer**
- **Activates on**: deploy, CI/CD, Docker, Kubernetes, GitHub Actions, AWS, Azure, GCP
- **Specializes in**: Deployment strategies and DevOps
- **Key tools**: GitHub Actions, deployment testing

#### 📦 **pwa-architect**
- **Activates on**: PWA, service worker, offline functionality, web manifest, push notifications
- **Specializes in**: Progressive Web App implementation
- **Key tools**: PWA testing, framework documentation

### Design & Documentation

#### 🎨 **ui-ux-specialist**
- **Activates on**: UI design, UX, accessibility, WCAG, design system, responsive layout
- **Specializes in**: User interface and experience optimization
- **Key tools**: UI component generation, accessibility testing

#### 📝 **documentation-specialist**
- **Activates on**: README, API docs, architecture docs, user guides, setup instructions
- **Specializes in**: Technical documentation creation
- **Key tools**: GitHub for doc management, reference lookup

### Project Management & Utilities

#### 📊 **project-coordinator**
- **Activates on**: project planning, SSDLC, sprint planning, milestone tracking
- **Specializes in**: Project coordination and team management
- **Key tools**: GitHub project management, task tracking

#### 📁 **directory-scanner**
- **Activates on**: directory structure, file organization, project layout, codebase structure
- **Specializes in**: Analyzing project organization
- **Key tools**: File system navigation and analysis

#### 🤖 **meta-agent**
- **Activates on**: create new agent, agent configuration, custom agent
- **Specializes in**: Creating new sub-agent configurations
- **Key tools**: Agent template generation

## 🛠️ Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd claude-agents
```

2. Copy the `.claude` directory to your project root:
```bash
cp -r .claude /path/to/your/project/
```

3. The agents will be automatically available in Claude Code

## 💡 Usage Examples

### Automatic Activation
Simply mention keywords in your request:
```
"I need to create a REST API for user management"
→ api-builder agent activates automatically

"Help me optimize this slow database query"
→ database-architect agent activates automatically

"Write unit tests for the authentication module"
→ test-engineer agent activates automatically
```

### Manual Activation
You can also explicitly request an agent:
```
"Use the secure-coder agent to review my authentication implementation"
```

### Creating New Agents
```
"Create a new agent for GraphQL schema validation"
→ meta-agent activates to help you create a custom agent
```

## 🔧 MCP Server Integration

This collection leverages several MCP (Model Context Protocol) servers:

- **mcp__github__**: Repository management, PR creation, issue tracking
- **mcp__playwright__**: Browser automation and E2E testing
- **mcp__context7__**: Library documentation retrieval
- **mcp__magic__**: UI component generation from 21st.dev

## 📋 Best Practices

1. **Let agents work proactively** - Many agents activate automatically when appropriate
2. **Use specific keywords** - The more specific your request, the better the agent selection
3. **Combine agents** - Multiple agents can work together on complex tasks
4. **Review agent suggestions** - Agents provide expert guidance but always review their output

## 🤝 Contributing

To add new agents or improve existing ones:

1. Use the meta-agent to create new agent configurations
2. Follow the existing pattern for descriptions and tool selection
3. Test the agent activation and functionality
4. Submit a PR with your improvements

## 📄 License

This collection is provided as-is for use with Claude Code. See LICENSE file for details.

## 🙏 Acknowledgments

Built following [Anthropic's Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code/sub-agents) and best practices.

---

*Happy coding with Claude Code agents! 🚀*