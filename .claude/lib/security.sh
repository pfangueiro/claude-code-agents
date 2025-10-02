#!/bin/bash
# Security Library - Input Sanitization and Validation
# Provides secure functions for all agents to use

set -euo pipefail

# Sanitize input to prevent command injection
# Removes shell metacharacters and control characters
sanitize_input() {
    local input="${1:-}"
    local max_length="${2:-1000}"

    # Remove null bytes
    input="${input//\x00/}"

    # Truncate to max length
    if [[ ${#input} -gt $max_length ]]; then
        input="${input:0:$max_length}"
    fi

    # Remove dangerous shell metacharacters
    # Keep only alphanumeric, spaces, and safe punctuation
    input=$(echo "$input" | tr -d '";`$(){}[]<>|&\\'\')

    # Remove newlines and carriage returns to prevent log injection
    input="${input//$'\n'/ }"
    input="${input//$'\r'/ }"

    # Remove repeated spaces
    input=$(echo "$input" | sed 's/  */ /g')

    # Trim leading/trailing whitespace
    input="${input#"${input%%[![:space:]]*}"}"
    input="${input%"${input##*[![:space:]]}"}"

    echo "$input"
}

# Validate input contains no dangerous patterns
validate_safe_input() {
    local input="${1:-}"

    # Check for command substitution patterns
    if echo "$input" | grep -qE '\$\(|\$\{|`|;;|&&|\|\|'; then
        echo "ERROR: Dangerous pattern detected in input" >&2
        return 1
    fi

    # Check for directory traversal
    if echo "$input" | grep -qE '\.\./|/\.\./'; then
        echo "ERROR: Directory traversal attempt detected" >&2
        return 1
    fi

    # Check for null bytes
    if [[ "$input" == *$'\x00'* ]]; then
        echo "ERROR: Null byte detected in input" >&2
        return 1
    fi

    return 0
}

# Redact sensitive patterns from logs
redact_secrets() {
    local text="${1:-}"

    # Redact API keys (common patterns)
    text=$(echo "$text" | sed -E 's/([Aa][Pp][Ii][_-]?[Kk][Ee][Yy][\s=:]+)[A-Za-z0-9+/]{20,}/\1[REDACTED]/g')

    # Redact tokens
    text=$(echo "$text" | sed -E 's/([Tt][Oo][Kk][Ee][Nn][\s=:]+)[A-Za-z0-9+/]{20,}/\1[REDACTED]/g')

    # Redact passwords
    text=$(echo "$text" | sed -E 's/([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd][\s=:]+)[^[:space:]]+/\1[REDACTED]/g')

    # Redact secrets
    text=$(echo "$text" | sed -E 's/([Ss][Ee][Cc][Rr][Ee][Tt][\s=:]+)[^[:space:]]+/\1[REDACTED]/g')

    # Redact Bearer tokens
    text=$(echo "$text" | sed -E 's/(Bearer\s+)[A-Za-z0-9+/._-]{20,}/\1[REDACTED]/g')

    # Redact SSH keys
    text=$(echo "$text" | sed -E 's/(ssh-[a-z]+\s+)[A-Za-z0-9+/]+/\1[REDACTED]/g')

    # Redact base64 encoded secrets (long base64 strings)
    text=$(echo "$text" | sed -E 's/[A-Za-z0-9+/]{50,}=[REDACTED_BASE64]/g')

    echo "$text"
}

# Secure file operations with validation
secure_write_file() {
    local file="${1:-}"
    local content="${2:-}"
    local mode="${3:-600}"

    # Validate file path
    if [[ "$file" == *".."* ]] || [[ "$file" == *"~"* ]]; then
        echo "ERROR: Invalid file path" >&2
        return 1
    fi

    # Create directory with secure permissions
    local dir=$(dirname "$file")
    if [[ ! -d "$dir" ]]; then
        mkdir -p -m 700 "$dir"
    fi

    # Write file with secure permissions
    echo "$content" > "$file"
    chmod "$mode" "$file"
}

# Secure logging with rotation
secure_log() {
    local log_file="${1:-}"
    local message="${2:-}"
    local max_lines="${3:-10000}"

    # Sanitize and redact the message
    message=$(sanitize_input "$message" 500)
    message=$(redact_secrets "$message")

    # Add timestamp
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local log_entry="${timestamp} ${message}"

    # Simple append with basic rotation (no file locking for compatibility)
    if [[ -f "$log_file" ]]; then
        local current_lines=$(wc -l < "$log_file" 2>/dev/null || echo 0)
        if [[ $current_lines -ge $max_lines ]]; then
            mv "$log_file" "${log_file}.old"
            touch "$log_file"
            chmod 600 "$log_file"
        fi
    fi

    # Append to log
    echo "$log_entry" >> "$log_file"
}

# Validate file path is within project
validate_project_path() {
    local path="${1:-}"
    local project_root="${2:-$(pwd)}"

    # Resolve to absolute path
    local abs_path=$(cd "$(dirname "$path")" 2>/dev/null && pwd || echo "")

    if [[ -z "$abs_path" ]]; then
        echo "ERROR: Invalid path" >&2
        return 1
    fi

    # Check if path is within project
    if [[ "$abs_path" != "$project_root"* ]]; then
        echo "ERROR: Path outside project boundary" >&2
        return 1
    fi

    return 0
}

# Generate secure random string
generate_secure_id() {
    local length="${1:-32}"

    # Use /dev/urandom for cryptographically secure random
    if [[ -r /dev/urandom ]]; then
        LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$length"
    else
        # Fallback to less secure random
        echo "$(date +%s)$$RANDOM" | sha256sum | cut -c1-"$length"
    fi
}

# Export functions for use by other scripts
export -f sanitize_input
export -f validate_safe_input
export -f redact_secrets
export -f secure_write_file
export -f secure_log
export -f validate_project_path
export -f generate_secure_id

# If sourced, return; if executed, run tests
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    return 0
fi

# Self-test when run directly
echo "Security Library Self-Test"
echo "=========================="

# Test sanitization
echo -n "Testing input sanitization... "
test_input='echo "test"; rm -rf /'
sanitized=$(sanitize_input "$test_input")
if [[ "$sanitized" == "echo test rm -rf /" ]]; then
    echo "✅ PASS"
else
    echo "❌ FAIL: Expected 'echo test rm -rf /', got '$sanitized'"
fi

# Test validation
echo -n "Testing dangerous pattern detection... "
if ! validate_safe_input 'test $(whoami)' 2>/dev/null; then
    echo "✅ PASS"
else
    echo "❌ FAIL: Should have detected command substitution"
fi

# Test secret redaction
echo -n "Testing secret redaction... "
test_text="api_key=sk-1234567890abcdef password=secret123"
redacted=$(redact_secrets "$test_text")
if [[ "$redacted" == *"[REDACTED]"* ]] && [[ "$redacted" != *"secret123"* ]]; then
    echo "✅ PASS"
else
    echo "❌ FAIL: Secrets not properly redacted"
fi

echo ""
echo "Security library ready for use!"