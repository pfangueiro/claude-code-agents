# Reading Strategies — Codebase-Type-Specific Approaches

How to trace execution paths and identify critical files for different codebase architectures.

---

## By Codebase Type

### Web App (MVC / Layered Architecture)

**Reading order:** routes -> controllers -> services -> repositories -> models -> middleware

1. Start at route definitions — find where HTTP endpoints are registered
2. Follow each route to its controller/handler — read the full handler
3. Trace service calls — the business logic layer, read every function
4. Follow to data access — repositories, ORMs, raw queries
5. Read models/schemas — what does the data actually look like?
6. Read middleware — auth, validation, error handling, logging

**Critical files:** Service layer (business logic), middleware (cross-cutting concerns), models (data shape)

**Common pitfalls:**
- Middleware can silently transform requests/responses — always check the middleware chain
- ORM magic can hide actual queries — check generated SQL if possible
- Validation may be split between controller, service, and model layers

### Microservices

**Reading order:** service registry -> API contracts -> events/messages -> per-service internal logic

1. Find the service registry or API gateway config — what services exist?
2. Read API contracts (OpenAPI specs, protobuf, GraphQL schemas) for the target service
3. Map inter-service communication — REST calls, gRPC, message queues, events
4. Dive into the target service following the Web App pattern above
5. Read event handlers — what does this service react to?
6. Read event publishers — what does this service broadcast?

**Critical files:** API contracts, event schemas, service-to-service client code, circuit breakers

**Common pitfalls:**
- Behavior may depend on other services — trace cross-service calls
- Event-driven flows can be non-obvious — grep for event names across all services
- Shared libraries between services may contain hidden business logic

### Monorepo

**Reading order:** root config -> dependency graph -> shared packages -> app packages

1. Read root config (`turbo.json`, `nx.json`, `lerna.json`, workspace configs)
2. Map the dependency graph between packages — what depends on what?
3. Read shared packages first (utils, types, core) — these affect everything
4. Then read the target app package following its architecture pattern
5. Check for cross-package imports — shared state, shared types, shared utilities

**Critical files:** Root config, shared package exports, workspace dependency declarations

**Common pitfalls:**
- Shared packages can change behavior across all apps simultaneously
- Build order may affect which version of a shared package is used
- Hoisted vs non-hoisted dependencies can cause version mismatches

### Library / SDK

**Reading order:** public exports -> types/interfaces -> implementation -> tests -> examples

1. Read the main export file (`index.ts`, `lib.rs`, `__init__.py`) — what's the public API?
2. Read type definitions — what contracts does the library promise?
3. Read the implementation of each public function/class
4. Read tests — they document intended behavior and edge cases
5. Read examples — they document intended usage patterns

**Critical files:** Public API surface, type definitions, core implementation modules

**Common pitfalls:**
- Internal vs public APIs may have different behavior guarantees
- Default parameter values can significantly change behavior
- Deprecated functions may still be the ones actually used by consumers

### CLI Application

**Reading order:** entry point -> command parser -> command handlers -> core logic

1. Find the entry point (`main`, `bin`, CLI framework setup)
2. Read command/subcommand registration — what commands exist?
3. For the target command: read the handler in full
4. Trace from handler to core logic — the actual work
5. Read configuration loading — env vars, config files, defaults
6. Read output formatting — how results are presented

**Critical files:** Command handlers, core logic modules, configuration loading

**Common pitfalls:**
- CLI frameworks often use decorators or metadata — trace through the framework's registration
- Default values and environment variables can change behavior silently
- Exit codes and error messages may be defined far from where errors occur

### Data Pipeline

**Reading order:** orchestration -> source connectors -> transforms -> sink connectors -> schemas

1. Read the orchestrator config (Airflow DAGs, cron jobs, workflow definitions)
2. Follow the pipeline order: source -> transform -> sink
3. For each stage, read the implementation in full
4. Read schema definitions — what does the data look like at each stage?
5. Read error handling — what happens when a stage fails?
6. Read monitoring/alerting — how are failures detected?

**Critical files:** Orchestration config, transform logic, schema definitions, error handlers

**Common pitfalls:**
- Transforms may happen in multiple places (source, transform stage, sink)
- Schema evolution can break downstream consumers
- Retry logic may cause duplicate processing — check for idempotency

---

## By Codebase Size

### Small (< 20 source files)

**Strategy:** Read everything.

1. List all files with Glob
2. Read every source file in full (use parallel Read calls)
3. Build the complete picture — no need to narrow scope
4. Focus Phase 4 (DEEP READ) on the files with the most logic

### Medium (20-50 source files)

**Strategy:** Identify the critical path, read all files in it.

1. Map the full file list in Phase 2
2. In Phase 3, trace the primary execution path — this typically touches 8-15 files
3. Read ALL files in the critical path in full
4. For files outside the critical path: read exports/interfaces only (unless they contain business logic)
5. Focus Phase 4 on the 5-10 most logic-heavy files

### Large (50+ source files)

**Strategy:** Narrow scope aggressively in Phase 1. Use parallel agents. Deep-read the top 10-15 files.

1. Phase 1 MUST narrow to < 50 files — use AskUserQuestion if needed
2. In Phase 2, launch parallel Explore agents:
   - Agent 1: Map directory structure and tech stack
   - Agent 2: Map entry points and exports
   - Agent 3: Map internal dependency graph
3. In Phase 3, trace only the paths relevant to the reading target
4. In Phase 4, deep-read only the top 10-15 critical files
5. For surrounding files: read enough to understand interfaces (types, exports, function signatures with their immediate implementation)

**Context management for large codebases:**
- Summarize completed phases before starting the next one
- Use the REPORT structure to accumulate findings incrementally
- If context gets large, focus on citations (`file:line`) rather than inlining full code

---

## Cross-Cutting Concerns

Regardless of codebase type, always check these:

### Configuration
- Where do config values come from? (env vars, files, defaults, feature flags)
- What config changes behavior? Read the config loading code.

### Error Handling
- What happens when things fail? Trace error paths, not just happy paths.
- Are errors swallowed silently? Grep for empty catch blocks.

### Authentication & Authorization
- Where is auth checked? Is it middleware, decorator, or inline?
- Are there bypasses? (admin routes, internal endpoints, dev mode)

### Logging & Observability
- What gets logged? What doesn't? (privacy implications)
- Are there metrics that reveal behavior? Read the instrumentation.

### Tests as Documentation
- Tests often encode business rules more precisely than comments.
- Read test files for critical modules — they document expected behavior and edge cases.
- `describe` / `it` blocks often read as specifications.
