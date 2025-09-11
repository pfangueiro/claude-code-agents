#!/bin/bash
# Context Detector Hook - Project context awareness for enhanced agent activation

# Environment variables:
# $PROJECT_PATH - Current project directory
# $CURRENT_FILES - Currently open/focused files
# $GIT_BRANCH - Current git branch
# $RECENT_ACTIVITY - Recent file modifications

# Create analytics directory
mkdir -p .claude/analytics
mkdir -p .claude/logs

# Generate context analysis ID and timestamp
CONTEXT_ID=$(uuidgen 2>/dev/null || echo "context-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Project Type Detection Function
detect_project_type() {
    local project_path="$1"
    local project_type="generic"
    
    # Check for framework indicators
    if [ -f "$project_path/package.json" ]; then
        if grep -q "next" "$project_path/package.json" 2>/dev/null; then
            project_type="nextjs"
        elif grep -q "react" "$project_path/package.json" 2>/dev/null; then
            project_type="react"
        elif grep -q "vue" "$project_path/package.json" 2>/dev/null; then
            project_type="vue"
        elif grep -q "express" "$project_path/package.json" 2>/dev/null; then
            project_type="nodejs-api"
        else
            project_type="nodejs"
        fi
    elif [ -f "$project_path/requirements.txt" ] || [ -f "$project_path/pyproject.toml" ]; then
        if [ -f "$project_path/manage.py" ]; then
            project_type="django"
        elif grep -q "fastapi" "$project_path/requirements.txt" 2>/dev/null; then
            project_type="fastapi"
        elif grep -q "flask" "$project_path/requirements.txt" 2>/dev/null; then
            project_type="flask"
        else
            project_type="python"
        fi
    elif [ -f "$project_path/Cargo.toml" ]; then
        project_type="rust"
    elif [ -f "$project_path/go.mod" ]; then
        project_type="go"
    fi
    
    echo "$project_type"
}

# File Context Analysis
analyze_file_context() {
    local project_path="$1"
    local file_context=""
    
    # Analyze recently modified files
    local recent_files=$(find "$project_path" -type f \( -name "*.js" -o -name "*.ts" -o -name "*.tsx" -o -name "*.jsx" -o -name "*.py" -o -name "*.rs" -o -name "*.go" \) -mtime -1 2>/dev/null)
    
    # Count file types for context
    local frontend_files=$(echo "$recent_files" | grep -c "\.\(tsx\|jsx\|vue\|component\)" 2>/dev/null || echo "0")
    local api_files=$(echo "$recent_files" | grep -c "\(api\|route\|controller\|endpoint\)" 2>/dev/null || echo "0")
    local test_files=$(echo "$recent_files" | grep -c "\(test\|spec\|\.test\.\|\.spec\.\)" 2>/dev/null || echo "0")
    local config_files=$(echo "$recent_files" | grep -c "\(config\|settings\|env\)" 2>/dev/null || echo "0")
    
    # Determine primary context
    if [ "$frontend_files" -gt 2 ]; then
        file_context="$file_context frontend-focused"
    fi
    if [ "$api_files" -gt 1 ]; then
        file_context="$file_context api-focused"
    fi
    if [ "$test_files" -gt 1 ]; then
        file_context="$file_context testing-focused"
    fi
    if [ "$config_files" -gt 0 ]; then
        file_context="$file_context configuration-focused"
    fi
    
    echo "$file_context"
}

# Development Stage Analysis
analyze_development_stage() {
    local project_path="$1"
    local stage="unknown"
    
    # Check git branch for stage indicators
    if [ -d "$project_path/.git" ]; then
        local branch=$(git -C "$project_path" branch --show-current 2>/dev/null || echo "main")
        
        case "$branch" in
            feature/*|feat/*)
                stage="feature-development"
                ;;
            bugfix/*|fix/*|hotfix/*)
                stage="bug-fixing"
                ;;
            release/*|rel/*)
                stage="release-preparation"
                ;;
            develop|development)
                stage="active-development"
                ;;
            main|master)
                stage="stable"
                ;;
            *)
                stage="development"
                ;;
        esac
    fi
    
    # Check for deployment indicators
    if [ -f "$project_path/Dockerfile" ] || [ -f "$project_path/docker-compose.yml" ]; then
        stage="$stage deployment-ready"
    fi
    
    # Check for testing setup
    if [ -d "$project_path/tests" ] || [ -d "$project_path/__tests__" ] || [ -d "$project_path/test" ]; then
        stage="$stage test-configured"
    fi
    
    echo "$stage"
}

# Workload Analysis
analyze_current_workload() {
    local workload_level="normal"
    
    # Check current agent processes
    local active_agents=$(ps aux | grep -c "claude.*agent" 2>/dev/null || echo "0")
    
    # Check system resources
    local cpu_usage=$(top -l 1 -n 0 | grep "CPU usage" | awk '{print $3}' | sed 's/%//' 2>/dev/null || echo "0")
    local memory_pressure=$(vm_stat 2>/dev/null | grep "Pages free" | awk '{print $3}' | sed 's/\.//' 2>/dev/null || echo "100000")
    
    if [ "$active_agents" -gt 5 ] || [ "${cpu_usage%.*}" -gt 80 ]; then
        workload_level="high"
    elif [ "$active_agents" -gt 2 ] || [ "${cpu_usage%.*}" -gt 50 ]; then
        workload_level="medium"
    fi
    
    echo "$workload_level"
}

# Perform comprehensive context analysis
PROJECT_TYPE=$(detect_project_type "$PROJECT_PATH")
FILE_CONTEXT=$(analyze_file_context "$PROJECT_PATH")
DEV_STAGE=$(analyze_development_stage "$PROJECT_PATH")
WORKLOAD_LEVEL=$(analyze_current_workload)

# Context-aware agent priority adjustment
adjust_agent_priorities() {
    local recommended="$1"
    local project_type="$2"
    local file_context="$3"
    local dev_stage="$4"
    local adjusted="$recommended"
    
    # Project type adjustments
    case "$project_type" in
        "nextjs"|"react"|"vue")
            if ! echo "$adjusted" | grep -q "frontend-architect"; then
                adjusted="frontend-architect,$adjusted"
            fi
            if ! echo "$adjusted" | grep -q "typescript-expert"; then
                adjusted="$adjusted,typescript-expert"
            fi
            ;;
        "fastapi"|"django"|"flask")
            if ! echo "$adjusted" | grep -q "python-expert"; then
                adjusted="python-expert,$adjusted"
            fi
            if ! echo "$adjusted" | grep -q "api-builder"; then
                adjusted="$adjusted,api-builder"
            fi
            ;;
    esac
    
    # Development stage adjustments
    case "$dev_stage" in
        *"release-preparation"*)
            adjusted="$adjusted,deployment-engineer,test-engineer,secure-coder"
            ;;
        *"bug-fixing"*)
            adjusted="refactor-specialist,$adjusted,test-engineer"
            ;;
        *"feature-development"*)
            adjusted="$adjusted,test-engineer"
            ;;
    esac
    
    # Remove duplicates and limit to reasonable number
    adjusted=$(echo "$adjusted" | tr ',' '\n' | sort -u | head -8 | tr '\n' ',' | sed 's/,$//')
    
    echo "$adjusted"
}

# Apply context-aware adjustments
ADJUSTED_AGENTS=$(adjust_agent_priorities "$RECOMMENDED_AGENTS" "$PROJECT_TYPE" "$FILE_CONTEXT" "$DEV_STAGE")

# Generate activation confidence score
calculate_confidence() {
    local agents="$1"
    local context_match=0
    local total_agents=$(echo "$agents" | tr ',' ' ' | wc -w)
    
    # Calculate confidence based on context matching
    for agent in $(echo "$agents" | tr ',' ' '); do
        local agent_file=".claude/agents/${agent}.md"
        if [ -f "$agent_file" ]; then
            local agent_desc=$(grep "description:" "$agent_file" | cut -d'"' -f2)
            
            # Check context alignment
            for tech in $DETECTED_TECH; do
                if echo "$agent_desc" | grep -qi "$tech"; then
                    context_match=$((context_match + 1))
                    break
                fi
            done
        fi
    done
    
    # Calculate confidence percentage
    if [ "$total_agents" -gt 0 ]; then
        local confidence=$((context_match * 100 / total_agents))
        echo "$confidence"
    else
        echo "0"
    fi
}

ACTIVATION_CONFIDENCE=$(calculate_confidence "$ADJUSTED_AGENTS")

# Log context analysis
CONTEXT_LOG=".claude/logs/context-analysis.jsonl"
echo "{
  \"timestamp\": \"$TIMESTAMP\",
  \"context_id\": \"$CONTEXT_ID\",
  \"project_type\": \"$PROJECT_TYPE\",
  \"file_context\": \"$FILE_CONTEXT\",
  \"dev_stage\": \"$DEV_STAGE\",
  \"workload_level\": \"$WORKLOAD_LEVEL\",
  \"original_agents\": \"$RECOMMENDED_AGENTS\",
  \"adjusted_agents\": \"$ADJUSTED_AGENTS\",
  \"activation_confidence\": $ACTIVATION_CONFIDENCE
}" >> "$CONTEXT_LOG"

# Console output with enhanced intelligence
echo "🧠 [CONTEXT] Project: $PROJECT_TYPE | Stage: $DEV_STAGE | Focus: $FILE_CONTEXT"
echo "⚡ [WORKLOAD] System load: $WORKLOAD_LEVEL | Activation confidence: ${ACTIVATION_CONFIDENCE}%"
echo "🎯 [FINAL SELECTION] Optimized agents: $ADJUSTED_AGENTS"

# Set final environment variables for agent coordination
export FINAL_AGENT_SELECTION="$ADJUSTED_AGENTS"
export ACTIVATION_CONFIDENCE="$ACTIVATION_CONFIDENCE"
export PROJECT_TYPE_DETECTED="$PROJECT_TYPE"
export DEVELOPMENT_STAGE="$DEV_STAGE"
export SYSTEM_WORKLOAD="$WORKLOAD_LEVEL"

# Trigger multi-agent coordination if needed
if [ $(echo "$ADJUSTED_AGENTS" | tr ',' ' ' | wc -w) -gt 1 ]; then
    if [ -f ".claude/hooks/multi_agent_coordinator.sh" ]; then
        .claude/hooks/multi_agent_coordinator.sh &
    fi
fi