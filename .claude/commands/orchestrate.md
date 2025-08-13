# Orchestrate Agents

Orchestrate multiple agents in parallel or sequence based on the task described in $ARGUMENTS.

Analyze the requirements and determine:
1. Which agents are needed
2. Which can run in parallel
3. What the sequence should be
4. How to handle handoffs

Use the project-coordinator agent to:
- Plan the orchestration strategy
- Identify parallel execution opportunities
- Manage agent handoffs
- Track progress across all agents
- Compile final results

Follow these orchestration patterns:
- **Parallel**: Tasks that don't depend on each other
- **Sequential**: Tasks with dependencies
- **Pipeline**: Output of one feeds into next
- **Fork-Join**: Split work, then merge results

Provide a detailed execution plan and coordinate the agents accordingly.