#!/bin/bash
# Rows Affected Enforcer Hook
# Ensures write operations verify persistence with rowsAffected >= 1

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if code verifies rowsAffected
check_rows_affected_validation() {
    local file="${1:-}"

    if [[ -z "$file" ]]; then
        echo "Error: File path required" >&2
        return 1
    fi

    local issues=()
    local line_num=0
    local in_write_operation=false

    while IFS= read -r line; do
        ((line_num++))

        # Detect write operations (language agnostic patterns)
        if echo "$line" | grep -qE "(INSERT|UPDATE|DELETE|save|create|update|destroy|persist|store)" && \
           ! echo "$line" | grep -qE "^[[:space:]]*(//|#|\*|--)" ; then
            in_write_operation=true
        fi

        # Check for rowsAffected validation
        if [[ "$in_write_operation" == true ]]; then
            if echo "$line" | grep -qE "(rowsAffected|affectedRows|affected_rows|changes|rowCount|modifiedCount)" ; then
                # Found validation
                in_write_operation=false
            elif echo "$line" | grep -qE "(\}|end|;$)" ; then
                # End of operation without validation
                issues+=("Line $line_num: Write operation without rowsAffected check")
                in_write_operation=false
            fi
        fi
    done < "$file"

    if [[ ${#issues[@]} -gt 0 ]]; then
        echo "❌ Found ${#issues[@]} write operations without rowsAffected validation:"
        printf '%s\n' "${issues[@]}"
        return 1
    else
        echo "✅ All write operations properly validate rowsAffected"
        return 0
    fi
}

# Generate rowsAffected wrapper for different languages
generate_wrapper() {
    local language="${1:-}"

    case "$language" in
        javascript|js|typescript|ts)
            cat <<'EOF'
/**
 * Wrapper to ensure rowsAffected validation
 * @param {Function} operation - Database operation
 * @param {number} minimumRows - Minimum rows that must be affected (default: 1)
 * @returns {Promise} Result if successful
 * @throws {Error} If rowsAffected < minimumRows
 */
async function enforceRowsAffected(operation, minimumRows = 1) {
    const result = await operation();

    const affected = result.rowsAffected || result.affectedRows || result.changes || 0;

    if (affected < minimumRows) {
        throw new Error(`Operation failed: Expected at least ${minimumRows} rows affected, got ${affected}`);
    }

    return result;
}

// Usage example:
// const result = await enforceRowsAffected(async () => {
//     return await db.users.update({ id: userId }, { name: newName });
// });
EOF
            ;;

        python|py)
            cat <<'EOF'
def enforce_rows_affected(operation, minimum_rows=1):
    """
    Wrapper to ensure rows_affected validation

    Args:
        operation: Database operation function
        minimum_rows: Minimum rows that must be affected (default: 1)

    Returns:
        Result if successful

    Raises:
        ValueError: If rows_affected < minimum_rows
    """
    result = operation()

    affected = getattr(result, 'rowcount', 0) or \
               getattr(result, 'rows_affected', 0) or \
               getattr(result, 'modified_count', 0) or 0

    if affected < minimum_rows:
        raise ValueError(f"Operation failed: Expected at least {minimum_rows} rows affected, got {affected}")

    return result

# Usage example:
# result = enforce_rows_affected(lambda: cursor.execute(
#     "UPDATE users SET name = %s WHERE id = %s", (new_name, user_id)
# ))
EOF
            ;;

        go)
            cat <<'EOF'
package db

import (
    "fmt"
    "database/sql"
)

// EnforceRowsAffected ensures minimum rows are affected by operation
func EnforceRowsAffected(operation func() (sql.Result, error), minimumRows int64) (sql.Result, error) {
    if minimumRows <= 0 {
        minimumRows = 1
    }

    result, err := operation()
    if err != nil {
        return nil, err
    }

    affected, err := result.RowsAffected()
    if err != nil {
        return nil, err
    }

    if affected < minimumRows {
        return nil, fmt.Errorf("operation failed: expected at least %d rows affected, got %d",
            minimumRows, affected)
    }

    return result, nil
}

// Usage example:
// result, err := EnforceRowsAffected(func() (sql.Result, error) {
//     return db.Exec("UPDATE users SET name = ? WHERE id = ?", newName, userID)
// }, 1)
EOF
            ;;

        ruby|rb)
            cat <<'EOF'
# Wrapper to ensure rows_affected validation
# @param minimum_rows [Integer] Minimum rows that must be affected (default: 1)
# @yield Database operation block
# @return Result if successful
# @raise [RuntimeError] If rows_affected < minimum_rows
def enforce_rows_affected(minimum_rows = 1)
  result = yield

  affected = result.cmd_tuples || result.rows_affected || result.changes || 0

  if affected < minimum_rows
    raise "Operation failed: Expected at least #{minimum_rows} rows affected, got #{affected}"
  end

  result
end

# Usage example:
# result = enforce_rows_affected do
#   User.where(id: user_id).update(name: new_name)
# end
EOF
            ;;

        *)
            echo "Error: Unsupported language: $language" >&2
            echo "Supported: javascript, typescript, python, go, ruby"
            return 1
            ;;
    esac
}

# Scan directory for missing validations
scan_directory() {
    local dir="${1:-.}"
    local extensions="${2:-js,ts,py,go,rb,java,php}"

    echo "Scanning for write operations without rowsAffected validation..."
    echo "Directory: $dir"
    echo "Extensions: $extensions"
    echo ""

    local total_files=0
    local files_with_issues=0

    while IFS= read -r file; do
        ((total_files++))
        echo -n "Checking $file... "

        if check_rows_affected_validation "$file" >/dev/null 2>&1; then
            echo "✅"
        else
            echo "❌"
            ((files_with_issues++))
            check_rows_affected_validation "$file" 2>&1 | sed 's/^/  /'
        fi
    done < <(find "$dir" -type f \( $(echo "$extensions" | sed 's/,/ -o -name *./g' | sed 's/^/-name *./' ) \) 2>/dev/null)

    echo ""
    echo "Summary:"
    echo "  Total files scanned: $total_files"
    echo "  Files with issues: $files_with_issues"

    if [[ $files_with_issues -eq 0 ]]; then
        echo "  ✅ All files properly validate rowsAffected"
        return 0
    else
        echo "  ❌ Found issues in $files_with_issues files"
        return 1
    fi
}

# Main function
main() {
    local command="${1:-}"
    shift || true

    case "$command" in
        check)
            check_rows_affected_validation "$@"
            ;;
        wrapper)
            generate_wrapper "$@"
            ;;
        scan)
            scan_directory "$@"
            ;;
        *)
            echo "Rows Affected Enforcer Hook"
            echo "Usage:"
            echo "  $0 check <file>           - Check file for validation"
            echo "  $0 wrapper <language>     - Generate wrapper code"
            echo "  $0 scan [dir] [exts]      - Scan directory"
            echo ""
            echo "Supported languages: javascript, typescript, python, go, ruby"
            ;;
    esac
}

# Export functions for sourcing
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    export -f check_rows_affected_validation
    export -f generate_wrapper
    export -f scan_directory
else
    main "$@"
fi