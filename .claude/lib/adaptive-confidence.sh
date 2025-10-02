#!/bin/bash
# Adaptive Confidence System - Learning from telemetry
# Adjusts confidence thresholds based on historical performance

set -eo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly TELEMETRY_DIR="${SCRIPT_DIR}/../telemetry"
readonly LEARNING_FILE="${TELEMETRY_DIR}/learning.json"
readonly MIN_SAMPLES=10
readonly CONFIDENCE_WINDOW=0.1  # +/- 10% adjustment range

# Initialize learning data
init_learning_data() {
    mkdir -p "$TELEMETRY_DIR"

    if [[ ! -f "$LEARNING_FILE" ]]; then
        cat > "$LEARNING_FILE" <<EOF
{
  "agents": {
    "mobile-ux": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "api-reliability": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "schema-guardian": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "performance": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "security": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "accessibility": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "documentation": {"threshold": 0.5, "success_rate": 0.0, "samples": 0}
  },
  "global": {
    "total_requests": 0,
    "correct_routing": 0,
    "false_positives": 0,
    "false_negatives": 0
  }
}
EOF
    fi
}

# Get adaptive threshold for agent
get_adaptive_threshold() {
    local agent="$1"
    local base_threshold="${2:-0.5}"

    init_learning_data

    # Read current threshold from learning data
    if command -v jq &>/dev/null && [[ -f "$LEARNING_FILE" ]]; then
        local threshold=$(jq -r ".agents.\"$agent\".threshold // $base_threshold" "$LEARNING_FILE" 2>/dev/null)
        echo "${threshold:-$base_threshold}"
    else
        echo "$base_threshold"
    fi
}

# Update learning data based on outcome
update_learning() {
    local agent="$1"
    local confidence="$2"
    local outcome="$3"  # success, false_positive, false_negative

    init_learning_data

    # Without jq, append to a simple log
    if ! command -v jq &>/dev/null; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)|$agent|$confidence|$outcome" >> "${TELEMETRY_DIR}/learning.log"
        return
    fi

    # Update learning data
    local current_data=$(cat "$LEARNING_FILE")
    local samples=$(echo "$current_data" | jq -r ".agents.\"$agent\".samples // 0")
    local success_rate=$(echo "$current_data" | jq -r ".agents.\"$agent\".success_rate // 0")

    # Calculate new success rate
    local new_samples=$((samples + 1))
    local new_success_rate=$success_rate

    case "$outcome" in
        success)
            new_success_rate=$(awk "BEGIN {printf \"%.3f\", ($success_rate * $samples + 1) / $new_samples}")
            ;;
        false_positive|false_negative)
            new_success_rate=$(awk "BEGIN {printf \"%.3f\", ($success_rate * $samples) / $new_samples}")
            ;;
    esac

    # Update JSON
    echo "$current_data" | jq \
        --arg agent "$agent" \
        --arg samples "$new_samples" \
        --arg success_rate "$new_success_rate" \
        '.agents[$agent].samples = ($samples | tonumber) |
         .agents[$agent].success_rate = ($success_rate | tonumber)' \
        > "${LEARNING_FILE}.tmp"

    mv "${LEARNING_FILE}.tmp" "$LEARNING_FILE"
}

# Adjust thresholds based on performance
adjust_thresholds() {
    init_learning_data

    if ! command -v jq &>/dev/null; then
        echo "jq not available, cannot adjust thresholds" >&2
        return 1
    fi

    local updated=false
    local current_data=$(cat "$LEARNING_FILE")

    # Process each agent
    for agent in mobile-ux api-reliability schema-guardian performance security accessibility documentation; do
        local samples=$(echo "$current_data" | jq -r ".agents.\"$agent\".samples // 0")
        local success_rate=$(echo "$current_data" | jq -r ".agents.\"$agent\".success_rate // 0")
        local current_threshold=$(echo "$current_data" | jq -r ".agents.\"$agent\".threshold // 0.5")

        # Only adjust if we have enough samples
        if [[ $samples -ge $MIN_SAMPLES ]]; then
            local new_threshold=$current_threshold

            # Adjust based on success rate
            if (( $(awk "BEGIN {print ($success_rate < 0.7)}") )); then
                # Poor performance - raise threshold
                new_threshold=$(awk "BEGIN {printf \"%.3f\", $current_threshold + $CONFIDENCE_WINDOW}")
                updated=true
            elif (( $(awk "BEGIN {print ($success_rate > 0.9)}") )); then
                # Great performance - lower threshold slightly
                new_threshold=$(awk "BEGIN {printf \"%.3f\", $current_threshold - ($CONFIDENCE_WINDOW / 2)}")
                updated=true
            fi

            # Clamp between 0.3 and 0.8
            if (( $(awk "BEGIN {print ($new_threshold < 0.3)}") )); then
                new_threshold="0.3"
            elif (( $(awk "BEGIN {print ($new_threshold > 0.8)}") )); then
                new_threshold="0.8"
            fi

            # Update if changed
            if [[ "$new_threshold" != "$current_threshold" ]]; then
                current_data=$(echo "$current_data" | jq \
                    --arg agent "$agent" \
                    --arg threshold "$new_threshold" \
                    '.agents[$agent].threshold = ($threshold | tonumber)')
            fi
        fi
    done

    if [[ "$updated" == true ]]; then
        echo "$current_data" > "$LEARNING_FILE"
        echo "Thresholds adjusted based on performance data"
    fi
}

# Analyze telemetry for patterns
analyze_patterns() {
    local events_file="${TELEMETRY_DIR}/events.jsonl"

    if [[ ! -f "$events_file" ]]; then
        echo "No telemetry data available"
        return
    fi

    echo "Telemetry Analysis Report"
    echo "========================"

    # Agent activation frequency
    echo ""
    echo "Agent Activation Frequency:"
    for agent in mobile-ux api-reliability schema-guardian performance security accessibility documentation; do
        local count=$(grep "\"agent\":\"$agent\"" "$events_file" 2>/dev/null | wc -l)
        if [[ $count -gt 0 ]]; then
            printf "  %-20s: %d activations\n" "$agent" "$count"
        fi
    done

    # Confidence distribution
    echo ""
    echo "Confidence Distribution:"
    if command -v jq &>/dev/null; then
        local avg_confidence=$(cat "$events_file" | jq -s 'map(.confidence) | add/length' 2>/dev/null || echo "0")
        echo "  Average confidence: $(printf "%.2f%%" "$(awk "BEGIN {print $avg_confidence * 100}")")"

        # Confidence buckets
        local high=$(cat "$events_file" | jq -s 'map(select(.confidence > 0.8)) | length' 2>/dev/null || echo "0")
        local medium=$(cat "$events_file" | jq -s 'map(select(.confidence <= 0.8 and .confidence > 0.5)) | length' 2>/dev/null || echo "0")
        local low=$(cat "$events_file" | jq -s 'map(select(.confidence <= 0.5)) | length' 2>/dev/null || echo "0")

        echo "  High (>80%): $high"
        echo "  Medium (50-80%): $medium"
        echo "  Low (<50%): $low"
    fi

    # Response time analysis
    echo ""
    echo "Performance Metrics:"
    if command -v jq &>/dev/null; then
        local avg_time=$(cat "$events_file" | jq -s 'map(.elapsed_ms) | add/length' 2>/dev/null || echo "0")
        echo "  Average response time: ${avg_time}ms"

        local min_time=$(cat "$events_file" | jq -s 'map(.elapsed_ms) | min' 2>/dev/null || echo "0")
        local max_time=$(cat "$events_file" | jq -s 'map(.elapsed_ms) | max' 2>/dev/null || echo "0")
        echo "  Min/Max: ${min_time}ms / ${max_time}ms"
    fi

    # Recommendations
    echo ""
    echo "Recommendations:"
    if command -v jq &>/dev/null && [[ -f "$LEARNING_FILE" ]]; then
        local learning_data=$(cat "$LEARNING_FILE")

        for agent in mobile-ux api-reliability schema-guardian performance security accessibility documentation; do
            local threshold=$(echo "$learning_data" | jq -r ".agents.\"$agent\".threshold // 0.5")
            local samples=$(echo "$learning_data" | jq -r ".agents.\"$agent\".samples // 0")

            if [[ $samples -lt $MIN_SAMPLES ]]; then
                echo "  • $agent: Need $((MIN_SAMPLES - samples)) more samples for learning"
            elif (( $(awk "BEGIN {print ($threshold != 0.5)}") )); then
                echo "  • $agent: Threshold adjusted to $threshold based on performance"
            fi
        done
    fi
}

# Generate performance report
generate_report() {
    local output_file="${1:-${TELEMETRY_DIR}/performance_report.txt}"

    {
        echo "Agent System Performance Report"
        echo "Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo "========================================"
        echo ""

        analyze_patterns

        echo ""
        echo "Learning Status:"
        echo "---------------"

        if [[ -f "$LEARNING_FILE" ]] && command -v jq &>/dev/null; then
            cat "$LEARNING_FILE" | jq -r '
                .agents | to_entries[] |
                "  \(.key): threshold=\(.value.threshold), success=\(.value.success_rate), samples=\(.value.samples)"
            '
        else
            echo "  Learning data not available"
        fi

        echo ""
        echo "System Health:"
        echo "-------------"

        local total_events=0
        if [[ -f "${TELEMETRY_DIR}/events.jsonl" ]]; then
            total_events=$(wc -l < "${TELEMETRY_DIR}/events.jsonl")
        fi

        echo "  Total events processed: $total_events"
        echo "  Learning system: $(command -v jq &>/dev/null && echo "Active" || echo "Inactive (jq required)")"
        echo "  Adaptive thresholds: $(command -v jq &>/dev/null && echo "Enabled" || echo "Disabled")"

    } > "$output_file"

    echo "Report saved to: $output_file"
}

# Export functions
export -f init_learning_data
export -f get_adaptive_threshold
export -f update_learning
export -f adjust_thresholds
export -f analyze_patterns
export -f generate_report

# Self-test when run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Adaptive Confidence System Self-Test"
    echo "===================================="

    # Initialize
    echo -n "Testing initialization... "
    init_learning_data
    if [[ -f "$LEARNING_FILE" ]]; then
        echo "✅ PASS"
    else
        echo "❌ FAIL"
    fi

    # Test threshold retrieval
    echo -n "Testing threshold retrieval... "
    threshold=$(get_adaptive_threshold "security" "0.5")
    if [[ -n "$threshold" ]]; then
        echo "✅ PASS (threshold: $threshold)"
    else
        echo "❌ FAIL"
    fi

    # Test learning update
    echo -n "Testing learning update... "
    update_learning "security" "0.75" "success"
    echo "✅ PASS"

    # Test pattern analysis
    echo ""
    echo "Running pattern analysis..."
    analyze_patterns

    echo ""
    echo "Adaptive confidence system ready!"
fi