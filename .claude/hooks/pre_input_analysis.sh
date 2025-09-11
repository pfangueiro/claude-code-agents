#!/bin/bash
# Pre-Input Analysis Hook - Semantic analysis of user input for intelligent agent activation

# Environment variables provided by Claude Code:
# $USER_INPUT - The user's input text
# $CURRENT_CONTEXT - Current conversation context
# $PROJECT_PATH - Current project directory path

# Enhanced auto-activation intelligence
# Create logs directory if it doesn't exist
mkdir -p .claude/logs
mkdir -p .claude/analytics

# Generate timestamp and analysis ID
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ANALYSIS_ID=$(uuidgen 2>/dev/null || echo "analysis-$(date +%s)-$$")

# Semantic Analysis Function
semantic_analysis() {
    local input="$1"
    local context="$2"
    
    # Intent Detection (create, fix, optimize, deploy, analyze, test, etc.)
    local intent="unknown"
    if echo "$input" | grep -qi "create\|build\|implement\|develop\|add\|make"; then
        intent="create"
    elif echo "$input" | grep -qi "fix\|debug\|solve\|repair\|resolve"; then
        intent="fix"
    elif echo "$input" | grep -qi "optimize\|improve\|enhance\|speed\|performance"; then
        intent="optimize"
    elif echo "$input" | grep -qi "deploy\|release\|publish\|ship"; then
        intent="deploy"
    elif echo "$input" | grep -qi "test\|validate\|verify\|check"; then
        intent="test"
    elif echo "$input" | grep -qi "analyze\|review\|understand\|explain"; then
        intent="analyze"
    fi
    
    # Technology Detection
    local tech_keywords=""
    echo "$input" | grep -qi "react\|jsx\|component" && tech_keywords="$tech_keywords react"
    echo "$input" | grep -qi "api\|endpoint\|rest\|graphql" && tech_keywords="$tech_keywords api"
    echo "$input" | grep -qi "database\|sql\|query\|schema" && tech_keywords="$tech_keywords database"
    echo "$input" | grep -qi "security\|auth\|login\|encrypt" && tech_keywords="$tech_keywords security"
    echo "$input" | grep -qi "performance\|slow\|speed\|optimize" && tech_keywords="$tech_keywords performance"
    echo "$input" | grep -qi "test\|spec\|coverage" && tech_keywords="$tech_keywords testing"
    echo "$input" | grep -qi "deploy\|docker\|kubernetes\|ci" && tech_keywords="$tech_keywords deployment"
    echo "$input" | grep -qi "typescript\|types\|interface" && tech_keywords="$tech_keywords typescript"
    echo "$input" | grep -qi "python\|django\|fastapi\|flask" && tech_keywords="$tech_keywords python"
    echo "$input" | grep -qi "mobile\|ios\|android\|react.native" && tech_keywords="$tech_keywords mobile"
    
    echo "$intent|$tech_keywords"
}

# Project Context Analysis
analyze_project_context() {
    local project_path="$1"
    local context=""
    
    # Detect recent file modifications
    if [ -d "$project_path" ]; then
        # Check recently modified files
        local recent_files=$(find "$project_path" -type f -name "*.js" -o -name "*.ts" -o -name "*.py" -o -name "*.md" -mtime -1 2>/dev/null | head -5)
        
        # Analyze file types for context
        if echo "$recent_files" | grep -q "\.tsx\?\|\.jsx\?"; then
            context="$context frontend"
        fi
        if echo "$recent_files" | grep -q "api\|route\|controller"; then
            context="$context api"
        fi
        if echo "$recent_files" | grep -q "test\|spec"; then
            context="$context testing"
        fi
        if echo "$recent_files" | grep -q "\.sql\|migration\|schema"; then
            context="$context database"
        fi
    fi
    
    echo "$context"
}

# Perform semantic analysis
ANALYSIS_RESULT=$(semantic_analysis "$USER_INPUT" "$CURRENT_CONTEXT")
INTENT=$(echo "$ANALYSIS_RESULT" | cut -d'|' -f1)
TECH_KEYWORDS=$(echo "$ANALYSIS_RESULT" | cut -d'|' -f2)

# Analyze project context
PROJECT_CONTEXT=$(analyze_project_context "$PROJECT_PATH")

# Log analysis for learning
ANALYSIS_LOG=".claude/logs/input-analysis.jsonl"
echo "{\"timestamp\":\"$TIMESTAMP\",\"analysis_id\":\"$ANALYSIS_ID\",\"user_input\":\"$USER_INPUT\",\"intent\":\"$INTENT\",\"tech_keywords\":\"$TECH_KEYWORDS\",\"project_context\":\"$PROJECT_CONTEXT\"}" >> "$ANALYSIS_LOG"

# Generate agent activation recommendations
ACTIVATION_RECOMMENDATIONS=""

# Intent-based activation logic
case "$INTENT" in
    "create")
        case "$TECH_KEYWORDS" in
            *"react"*) ACTIVATION_RECOMMENDATIONS="frontend-architect,ui-ux-specialist,typescript-expert" ;;
            *"api"*) ACTIVATION_RECOMMENDATIONS="api-builder,secure-coder,database-architect" ;;
            *"database"*) ACTIVATION_RECOMMENDATIONS="database-architect,performance-optimizer" ;;
            *) ACTIVATION_RECOMMENDATIONS="project-coordinator,context-analyzer" ;;
        esac
        ;;
    "fix"|"debug")
        case "$TECH_KEYWORDS" in
            *"performance"*) ACTIVATION_RECOMMENDATIONS="performance-optimizer,health-monitor" ;;
            *"security"*) ACTIVATION_RECOMMENDATIONS="secure-coder,integration-specialist" ;;
            *"database"*) ACTIVATION_RECOMMENDATIONS="database-architect,performance-optimizer" ;;
            *) ACTIVATION_RECOMMENDATIONS="refactor-specialist,test-engineer" ;;
        esac
        ;;
    "optimize")
        ACTIVATION_RECOMMENDATIONS="ai-optimizer,performance-optimizer,cost-optimizer"
        case "$TECH_KEYWORDS" in
            *"database"*) ACTIVATION_RECOMMENDATIONS="$ACTIVATION_RECOMMENDATIONS,database-architect" ;;
            *"api"*) ACTIVATION_RECOMMENDATIONS="$ACTIVATION_RECOMMENDATIONS,api-builder" ;;
            *"frontend"*) ACTIVATION_RECOMMENDATIONS="$ACTIVATION_RECOMMENDATIONS,frontend-architect" ;;
        esac
        ;;
    "analyze")
        ACTIVATION_RECOMMENDATIONS="context-analyzer,workflow-learner"
        ;;
    *)
        ACTIVATION_RECOMMENDATIONS="context-analyzer,project-coordinator"
        ;;
esac

# Add quality gates for certain intents
if [ "$INTENT" = "create" ] || [ "$INTENT" = "fix" ]; then
    ACTIVATION_RECOMMENDATIONS="$ACTIVATION_RECOMMENDATIONS,test-engineer"
fi

# Log activation recommendations
echo "{\"timestamp\":\"$TIMESTAMP\",\"analysis_id\":\"$ANALYSIS_ID\",\"recommendations\":\"$ACTIVATION_RECOMMENDATIONS\",\"confidence\":\"high\"}" >> ".claude/logs/activation-recommendations.jsonl"

# Output for Claude Code integration
echo "🧠 [INTELLIGENCE] Analyzed input → Intent: $INTENT | Tech: $TECH_KEYWORDS | Context: $PROJECT_CONTEXT"
echo "🎯 [ACTIVATION] Recommended agents: $ACTIVATION_RECOMMENDATIONS"

# Set environment variables for agent selection
export RECOMMENDED_AGENTS="$ACTIVATION_RECOMMENDATIONS"
export USER_INTENT="$INTENT"
export DETECTED_TECH="$TECH_KEYWORDS"
export PROJECT_CONTEXT_ANALYSIS="$PROJECT_CONTEXT"