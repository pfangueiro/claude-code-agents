#!/bin/bash
# Schema Introspection Hook
# Provides database schema inspection utilities for all agents

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect database type from environment or config
detect_database_type() {
    if [[ -n "${DATABASE_URL:-}" ]]; then
        if [[ "$DATABASE_URL" =~ postgres ]]; then
            echo "postgresql"
        elif [[ "$DATABASE_URL" =~ mysql ]]; then
            echo "mysql"
        elif [[ "$DATABASE_URL" =~ mongodb ]]; then
            echo "mongodb"
        elif [[ "$DATABASE_URL" =~ sqlite ]]; then
            echo "sqlite"
        else
            echo "unknown"
        fi
    elif [[ -f "database.yml" ]] || [[ -f "config/database.yml" ]]; then
        echo "rails"
    elif [[ -f "prisma/schema.prisma" ]]; then
        echo "prisma"
    else
        echo "unknown"
    fi
}

# Get PostgreSQL schema
get_postgresql_schema() {
    local database="${1:-}"
    local table="${2:-}"

    if [[ -z "$database" ]]; then
        echo "Error: Database name required" >&2
        return 1
    fi

    if [[ -n "$table" ]]; then
        # Get specific table schema
        psql -d "$database" -c "\d+ $table" 2>/dev/null || {
            echo "Error: Failed to get schema for table $table" >&2
            return 1
        }
    else
        # Get all tables
        psql -d "$database" -c "\dt" 2>/dev/null || {
            echo "Error: Failed to get database schema" >&2
            return 1
        }
    fi
}

# Get MySQL schema
get_mysql_schema() {
    local database="${1:-}"
    local table="${2:-}"

    if [[ -z "$database" ]]; then
        echo "Error: Database name required" >&2
        return 1
    fi

    if [[ -n "$table" ]]; then
        mysql -e "DESCRIBE $table" "$database" 2>/dev/null || {
            echo "Error: Failed to get schema for table $table" >&2
            return 1
        }
    else
        mysql -e "SHOW TABLES" "$database" 2>/dev/null || {
            echo "Error: Failed to get database schema" >&2
            return 1
        }
    fi
}

# Get Prisma schema
get_prisma_schema() {
    if [[ -f "prisma/schema.prisma" ]]; then
        cat prisma/schema.prisma
    else
        echo "Error: prisma/schema.prisma not found" >&2
        return 1
    fi
}

# Compare schemas (for drift detection)
compare_schemas() {
    local schema1="${1:-}"
    local schema2="${2:-}"

    if [[ -z "$schema1" ]] || [[ -z "$schema2" ]]; then
        echo "Error: Two schema files required for comparison" >&2
        return 1
    fi

    diff -u "$schema1" "$schema2" || {
        echo "Schema drift detected" >&2
        return 1
    }
}

# Extract table columns
extract_columns() {
    local schema_file="${1:-}"
    local table="${2:-}"

    if [[ -z "$schema_file" ]] || [[ -z "$table" ]]; then
        echo "Error: Schema file and table name required" >&2
        return 1
    fi

    # Extract columns based on schema format
    if grep -q "CREATE TABLE" "$schema_file"; then
        # SQL format
        sed -n "/CREATE TABLE.*$table/,/);/p" "$schema_file" | \
            grep -E "^\s+\w+" | \
            awk '{print $1}'
    elif grep -q "model $table" "$schema_file"; then
        # Prisma format
        sed -n "/model $table/,/^}/p" "$schema_file" | \
            grep -E "^\s+\w+" | \
            awk '{print $1}'
    else
        echo "Error: Unknown schema format" >&2
        return 1
    fi
}

# Check for missing indexes
check_indexes() {
    local database="${1:-}"
    local table="${2:-}"
    local db_type=$(detect_database_type)

    case "$db_type" in
        postgresql)
            psql -d "$database" -c "\di $table*" 2>/dev/null
            ;;
        mysql)
            mysql -e "SHOW INDEXES FROM $table" "$database" 2>/dev/null
            ;;
        *)
            echo "Error: Unsupported database type: $db_type" >&2
            return 1
            ;;
    esac
}

# Validate foreign keys
validate_foreign_keys() {
    local database="${1:-}"
    local db_type=$(detect_database_type)

    case "$db_type" in
        postgresql)
            psql -d "$database" -c "
                SELECT
                    conname AS constraint_name,
                    conrelid::regclass AS table_name,
                    confrelid::regclass AS referenced_table
                FROM pg_constraint
                WHERE contype = 'f'
                ORDER BY conrelid::regclass::text, conname;
            " 2>/dev/null
            ;;
        mysql)
            mysql -e "
                SELECT
                    CONSTRAINT_NAME,
                    TABLE_NAME,
                    REFERENCED_TABLE_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE REFERENCED_TABLE_NAME IS NOT NULL
                AND TABLE_SCHEMA = '$database';
            " 2>/dev/null
            ;;
        *)
            echo "Error: Unsupported database type: $db_type" >&2
            return 1
            ;;
    esac
}

# Main function
main() {
    local command="${1:-}"
    shift || true

    case "$command" in
        detect)
            detect_database_type
            ;;
        schema)
            local db_type=$(detect_database_type)
            case "$db_type" in
                postgresql) get_postgresql_schema "$@" ;;
                mysql) get_mysql_schema "$@" ;;
                prisma) get_prisma_schema ;;
                *) echo "Error: Unsupported database type: $db_type" >&2; exit 1 ;;
            esac
            ;;
        compare)
            compare_schemas "$@"
            ;;
        columns)
            extract_columns "$@"
            ;;
        indexes)
            check_indexes "$@"
            ;;
        foreign-keys)
            validate_foreign_keys "$@"
            ;;
        *)
            echo "Schema Introspection Hook"
            echo "Usage:"
            echo "  $0 detect                    - Detect database type"
            echo "  $0 schema [db] [table]       - Get schema information"
            echo "  $0 compare <file1> <file2>   - Compare two schemas"
            echo "  $0 columns <file> <table>    - Extract table columns"
            echo "  $0 indexes <db> <table>      - Check indexes"
            echo "  $0 foreign-keys <db>         - Validate foreign keys"
            ;;
    esac
}

# Export functions for sourcing
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    export -f detect_database_type
    export -f get_postgresql_schema
    export -f get_mysql_schema
    export -f get_prisma_schema
    export -f compare_schemas
    export -f extract_columns
    export -f check_indexes
    export -f validate_foreign_keys
else
    main "$@"
fi