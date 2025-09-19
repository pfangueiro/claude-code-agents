#!/bin/bash
# Claude Agents Router - The Brain
# Understands intent and activates the right agents

INPUT="$1"
COMMAND="${2:-auto}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Detect intent from natural language
detect_intent() {
    local input_lower=$(echo "$1" | tr '[:upper:]' '[:lower:]')

    # Architect patterns
    if echo "$input_lower" | grep -E "create|build|implement|design|setup|scaffold|architect" > /dev/null; then
        echo "architect"
    # Guardian patterns
    elif echo "$input_lower" | grep -E "test|fix|secure|optimize|debug|audit|validate|improve" > /dev/null; then
        echo "guardian"
    # Connector patterns
    elif echo "$input_lower" | grep -E "deploy|integrate|connect|publish|release|ship" > /dev/null; then
        echo "connector"
    # Documenter patterns
    elif echo "$input_lower" | grep -E "document|explain|describe|comment|readme" > /dev/null; then
        echo "documenter"
    # Default to architect for creation tasks
    else
        echo "architect"
    fi
}

# Route to appropriate workflow
route_request() {
    local intent=$(detect_intent "$1")
    local workflow=""

    case "$intent" in
        architect)
            workflow="Architect → Guardian → Connector"
            echo -e "${BLUE}Intent:${NC} Build something new"
            echo -e "${BLUE}Workflow:${NC} $workflow"
            ;;
        guardian)
            workflow="Guardian"
            echo -e "${BLUE}Intent:${NC} Fix or improve"
            echo -e "${BLUE}Workflow:${NC} $workflow"
            ;;
        connector)
            workflow="Connector → Guardian"
            echo -e "${BLUE}Intent:${NC} Deploy or integrate"
            echo -e "${BLUE}Workflow:${NC} $workflow"
            ;;
        documenter)
            workflow="Documenter"
            echo -e "${BLUE}Intent:${NC} Document or explain"
            echo -e "${BLUE}Workflow:${NC} $workflow"
            ;;
    esac

    # Log to history for learning
    mkdir -p .claude/history
    echo "$(date -u +%Y%m%d-%H%M%S)|$intent|$1" >> .claude/history/requests.log

    echo -e "${GREEN}✓${NC} Agents activated for: $1"
}

# Handle special commands
case "$COMMAND" in
    status)
        echo "Claude Agents: Active"
        echo "Agents: Architect, Guardian, Connector, Documenter"
        echo "History: $(wc -l < .claude/history/requests.log 2>/dev/null || echo 0) requests"
        ;;
    debug)
        tail -10 .claude/history/requests.log 2>/dev/null || echo "No history yet"
        ;;
    history)
        cat .claude/history/requests.log 2>/dev/null || echo "No history yet"
        ;;
    reset)
        rm -f .claude/history/*
        echo "History cleared"
        ;;
    auto|*)
        if [ -z "$INPUT" ]; then
            echo "Usage: $0 \"your request\" [command]"
            echo "Commands: status, debug, history, reset"
        else
            route_request "$INPUT"
        fi
        ;;
esac
