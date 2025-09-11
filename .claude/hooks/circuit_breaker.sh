#!/bin/bash
# Circuit Breaker Hook - External service failure management and fallback coordination

# Environment variables:
# $SERVICE_NAME - Name of the external service (github, context7, playwright, magic)
# $SERVICE_CALL_RESULT - Result of the service call (success/failure)
# $ERROR_MESSAGE - Error message if call failed
# $RESPONSE_TIME - Service response time in milliseconds

# Create circuit breaker directories
mkdir -p .claude/circuit-breakers
mkdir -p .claude/logs
mkdir -p .claude/fallbacks

# Generate circuit breaker event ID
BREAKER_EVENT_ID=$(uuidgen 2>/dev/null || echo "breaker-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Circuit breaker state management
get_circuit_state() {
    local service="$1"
    local state_file=".claude/circuit-breakers/${service}.state"
    
    if [ -f "$state_file" ]; then
        cat "$state_file"
    else
        echo "CLOSED"
    fi
}

set_circuit_state() {
    local service="$1"
    local state="$2"
    local state_file=".claude/circuit-breakers/${service}.state"
    
    echo "$state" > "$state_file"
    echo "$TIMESTAMP" > ".claude/circuit-breakers/${service}.last_change"
}

# Circuit breaker failure counting
increment_failure_count() {
    local service="$1"
    local failure_file=".claude/circuit-breakers/${service}.failures"
    
    local current_count=0
    if [ -f "$failure_file" ]; then
        current_count=$(cat "$failure_file")
    fi
    
    local new_count=$((current_count + 1))
    echo "$new_count" > "$failure_file"
    echo "$new_count"
}

reset_failure_count() {
    local service="$1"
    local failure_file=".claude/circuit-breakers/${service}.failures"
    
    echo "0" > "$failure_file"
}

# Circuit breaker logic
process_service_call() {
    local service="$1"
    local result="$2"
    local response_time="$3"
    local error_msg="$4"
    
    local current_state=$(get_circuit_state "$service")
    local action_taken=""
    
    case "$current_state" in
        "CLOSED")
            # Normal operation state
            if [ "$result" = "success" ]; then
                # Reset failure count on success
                reset_failure_count "$service"
                action_taken="SUCCESS_RECORDED"
                
                # Check for slow response (potential degradation)
                if [ "${response_time:-0}" -gt 5000 ]; then
                    action_taken="$action_taken SLOW_RESPONSE_WARNING"
                fi
            else
                # Handle failure
                local failure_count=$(increment_failure_count "$service")
                action_taken="FAILURE_RECORDED(count:$failure_count)"
                
                # Check failure threshold (5 failures in short period)
                if [ "$failure_count" -ge 5 ]; then
                    set_circuit_state "$service" "OPEN"
                    action_taken="$action_taken CIRCUIT_OPENED"
                    
                    # Schedule recovery attempt
                    (sleep 300 && .claude/hooks/circuit_breaker.sh recovery "$service") &
                fi
            fi
            ;;
        "OPEN")
            # Circuit is open, all calls fail fast
            action_taken="CALL_BLOCKED_CIRCUIT_OPEN"
            
            # Check if it's time to attempt recovery
            local last_change_file=".claude/circuit-breakers/${service}.last_change"
            if [ -f "$last_change_file" ]; then
                local last_change=$(cat "$last_change_file")
                local current_time=$(date +%s)
                local last_change_time=$(date -d "$last_change" +%s 2>/dev/null || echo "$current_time")
                
                # Try recovery after 5 minutes
                if [ $((current_time - last_change_time)) -gt 300 ]; then
                    set_circuit_state "$service" "HALF_OPEN"
                    action_taken="$action_taken ATTEMPTING_RECOVERY"
                fi
            fi
            ;;
        "HALF_OPEN")
            # Testing recovery state
            if [ "$result" = "success" ]; then
                set_circuit_state "$service" "CLOSED"
                reset_failure_count "$service"
                action_taken="CIRCUIT_RECOVERED"
            else
                set_circuit_state "$service" "OPEN"
                action_taken="RECOVERY_FAILED_CIRCUIT_REOPENED"
                
                # Longer backoff for failed recovery
                (sleep 900 && .claude/hooks/circuit_breaker.sh recovery "$service") &
            fi
            ;;
    esac
    
    echo "$current_state|$action_taken"
}

# Fallback Strategy Implementation
implement_fallback() {
    local service="$1"
    local fallback_strategy=""
    
    case "$service" in
        "github")
            # GitHub fallback - disable issue tracking, continue with local tracking
            export GITHUB_TRACKING="false"
            fallback_strategy="LOCAL_TRACKING_ONLY"
            ;;
        "context7")
            # Context7 fallback - use cached documentation or web search
            export CONTEXT7_FALLBACK="web_search"
            fallback_strategy="WEB_SEARCH_FALLBACK"
            ;;
        "playwright")
            # Playwright fallback - disable browser automation, use alternative testing
            export PLAYWRIGHT_FALLBACK="headless_mode"
            fallback_strategy="HEADLESS_TESTING"
            ;;
        "magic")
            # Magic UI fallback - use manual component creation
            export MAGIC_UI_FALLBACK="manual_creation"
            fallback_strategy="MANUAL_UI_CREATION"
            ;;
        *)
            fallback_strategy="NO_FALLBACK_AVAILABLE"
            ;;
    esac
    
    # Create fallback configuration
    if [ "$fallback_strategy" != "NO_FALLBACK_AVAILABLE" ]; then
        cat > ".claude/fallbacks/${service}-fallback.config" << EOF
{
  "service": "$service",
  "fallback_strategy": "$fallback_strategy",
  "activated_at": "$TIMESTAMP",
  "status": "active"
}
EOF
    fi
    
    echo "$fallback_strategy"
}

# Process the service call through circuit breaker
if [ ! -z "$SERVICE_NAME" ] && [ ! -z "$SERVICE_CALL_RESULT" ]; then
    CIRCUIT_RESULT=$(process_service_call "$SERVICE_NAME" "$SERVICE_CALL_RESULT" "$RESPONSE_TIME" "$ERROR_MESSAGE")
    CIRCUIT_STATE=$(echo "$CIRCUIT_RESULT" | cut -d'|' -f1)
    ACTION_TAKEN=$(echo "$CIRCUIT_RESULT" | cut -d'|' -f2)
    
    # Implement fallback if circuit is open
    FALLBACK_STRATEGY=""
    if [ "$CIRCUIT_STATE" = "OPEN" ]; then
        FALLBACK_STRATEGY=$(implement_fallback "$SERVICE_NAME")
    fi
    
    # Log circuit breaker event
    CIRCUIT_LOG=".claude/logs/circuit-breaker.jsonl"
    echo "{
      \"timestamp\": \"$TIMESTAMP\",
      \"event_id\": \"$BREAKER_EVENT_ID\",
      \"service\": \"$SERVICE_NAME\",
      \"call_result\": \"$SERVICE_CALL_RESULT\",
      \"response_time\": ${RESPONSE_TIME:-0},
      \"error_message\": \"$ERROR_MESSAGE\",
      \"circuit_state\": \"$CIRCUIT_STATE\",
      \"action_taken\": \"$ACTION_TAKEN\",
      \"fallback_strategy\": \"$FALLBACK_STRATEGY\"
    }" >> "$CIRCUIT_LOG"
    
    # Console output for circuit breaker actions
    case "$CIRCUIT_STATE" in
        "OPEN")
            echo "🚫 [CIRCUIT BREAKER] $SERVICE_NAME circuit OPEN - calls blocked"
            if [ ! -z "$FALLBACK_STRATEGY" ]; then
                echo "🔄 [FALLBACK] Activated: $FALLBACK_STRATEGY"
            fi
            ;;
        "HALF_OPEN")
            echo "🟡 [CIRCUIT BREAKER] $SERVICE_NAME circuit HALF-OPEN - testing recovery"
            ;;
        "CLOSED")
            if echo "$ACTION_TAKEN" | grep -q "CIRCUIT_RECOVERED"; then
                echo "✅ [CIRCUIT BREAKER] $SERVICE_NAME circuit RECOVERED - normal operation restored"
            fi
            ;;
    esac
    
    # Alert on circuit state changes
    if echo "$ACTION_TAKEN" | grep -q "CIRCUIT_OPENED\|CIRCUIT_RECOVERED"; then
        cat > ".claude/alerts/circuit-breaker-${SERVICE_NAME}-${BREAKER_EVENT_ID}.json" << EOF
{
  "alert_type": "circuit_breaker_state_change",
  "timestamp": "$TIMESTAMP",
  "service": "$SERVICE_NAME",
  "new_state": "$CIRCUIT_STATE",
  "action": "$ACTION_TAKEN",
  "fallback_strategy": "$FALLBACK_STRATEGY"
}
EOF
    fi
    
    # Set circuit breaker environment variables
    export SERVICE_CIRCUIT_STATE="$CIRCUIT_STATE"
    export SERVICE_FALLBACK_ACTIVE="$FALLBACK_STRATEGY"
    export CIRCUIT_BREAKER_ACTION="$ACTION_TAKEN"
fi

# Recovery mode handling
if [ "$1" = "recovery" ] && [ ! -z "$2" ]; then
    local service_to_recover="$2"
    echo "🔄 [CIRCUIT RECOVERY] Attempting recovery for $service_to_recover"
    
    # Test service connectivity
    local recovery_test="false"
    case "$service_to_recover" in
        "github")
            if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
                recovery_test="true"
            fi
            ;;
        "context7"|"playwright"|"magic")
            # These would need actual connectivity tests
            recovery_test="true"  # Simplified for now
            ;;
    esac
    
    if [ "$recovery_test" = "true" ]; then
        set_circuit_state "$service_to_recover" "HALF_OPEN"
        echo "✅ [CIRCUIT RECOVERY] $service_to_recover circuit set to HALF-OPEN for testing"
    else
        echo "❌ [CIRCUIT RECOVERY] $service_to_recover still not responding, maintaining OPEN state"
        # Schedule another recovery attempt
        (sleep 900 && .claude/hooks/circuit_breaker.sh recovery "$service_to_recover") &
    fi
fi