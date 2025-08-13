# Execute Workflow

Execute a complete development workflow based on the task type provided in $ARGUMENTS.

Parse the arguments to determine if this is a:
- "feature" - Run the feature development pipeline
- "bug" - Run the bug fix workflow  
- "review" - Run the code review workflow
- "security" - Run security audit workflow
- "performance" - Run performance optimization workflow

Based on the workflow type, orchestrate the appropriate agents in sequence:

## Feature Workflow
1. Use project-coordinator to plan the implementation
2. Use database-architect if data models are needed
3. Use api-builder for backend implementation
4. Use frontend-architect for UI components
5. Use test-engineer to write comprehensive tests
6. Use secure-coder to validate security
7. Use deployment-engineer to prepare deployment

## Bug Workflow
1. Use directory-scanner to understand the codebase structure
2. Use performance-optimizer or secure-coder based on bug type
3. Use refactor-specialist to fix the issue
4. Use test-engineer to validate the fix
5. Use deployment-engineer for hotfix deployment

## Review Workflow
1. Use secure-coder for security review
2. Use performance-optimizer for performance impact
3. Use refactor-specialist for code quality
4. Use test-engineer for test coverage validation

## Security Workflow
1. Use secure-coder for comprehensive audit
2. Use test-engineer for security test implementation
3. Use deployment-engineer for security patches

## Performance Workflow
1. Use performance-optimizer to identify bottlenecks
2. Use refactor-specialist to optimize code
3. Use infrastructure-expert for caching/scaling
4. Use test-engineer for performance tests

Coordinate the agents and provide a summary of the workflow execution.