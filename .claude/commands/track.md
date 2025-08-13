# Track Task Execution

Manage and view task tracking based on the arguments provided in $ARGUMENTS.

Parse the arguments to determine the action:
- "status" - Show current task status
- "costs" - Show token usage and costs
- "enable github" - Enable GitHub issue tracking
- "disable github" - Disable GitHub issue tracking
- "report [date]" - Generate report for specific date
- "clear" - Clear today's metrics (with confirmation)

## For "status" command:
1. Read today's metrics from .claude/metrics/
2. Show all in-progress tasks
3. Display recent completions
4. Show any failed tasks
5. Display current handoff chains

## For "costs" command:
1. Read token usage from .claude/metrics/token-costs.csv
2. Calculate costs by model (Haiku/Sonnet/Opus)
3. Show per-agent token usage
4. Display daily/weekly/monthly totals
5. Project estimated costs at current rate

## For "enable github" command:
1. Check if 'gh' CLI is installed
2. Verify GitHub authentication
3. Set GITHUB_TRACKING=true in environment
4. Create tracking label structure in repo
5. Start creating issues for new tasks

## For "report" command:
1. Generate comprehensive report for specified date
2. Include task success rates
3. Show agent performance metrics
4. Display workflow patterns
5. Calculate ROI (time saved vs token cost)

## Output Format:
Provide clear, formatted output with:
- Summary statistics
- Visual indicators (✅ ❌ ⏳ 🔄)
- Cost breakdowns
- Performance metrics
- Actionable insights

Always show the most relevant information first and provide suggestions for optimization based on the patterns observed.