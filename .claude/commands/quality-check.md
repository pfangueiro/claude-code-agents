# Quality Check

Run a comprehensive quality check on the codebase or specific files mentioned in $ARGUMENTS.

Execute quality gates in parallel using:
1. **secure-coder** - Security vulnerabilities scan
2. **performance-optimizer** - Performance bottlenecks
3. **refactor-specialist** - Code quality and smells
4. **test-engineer** - Test coverage analysis

Compile results into a quality report with:
- Security score and findings
- Performance metrics and issues
- Code quality score
- Test coverage percentage
- Overall quality gate status (PASS/FAIL)

If any critical issues are found, provide remediation steps and optionally fix them.