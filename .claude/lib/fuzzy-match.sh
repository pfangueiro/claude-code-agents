#!/bin/bash
# Fuzzy Matching Library - Typo tolerance and semantic expansion
# Provides fuzzy string matching and keyword expansion

set -eo pipefail

# Calculate Levenshtein distance between two strings
levenshtein_distance() {
    local str1="${1,,}"  # Convert to lowercase
    local str2="${2,,}"
    local len1=${#str1}
    local len2=${#str2}

    # Quick checks
    [[ "$str1" == "$str2" ]] && echo 0 && return
    [[ $len1 -eq 0 ]] && echo $len2 && return
    [[ $len2 -eq 0 ]] && echo $len1 && return

    # For performance, limit to short strings
    if [[ $len1 -gt 20 ]] || [[ $len2 -gt 20 ]]; then
        echo 999
        return
    fi

    # Simple approximation for Bash (not true Levenshtein but fast)
    local common=0
    local i
    for ((i=0; i<len1 && i<len2; i++)); do
        [[ "${str1:i:1}" == "${str2:i:1}" ]] && ((common++))
    done

    local max_len=$len1
    [[ $len2 -gt $max_len ]] && max_len=$len2

    local distance=$(( max_len - common ))
    echo $distance
}

# Fuzzy match with tolerance
fuzzy_match() {
    local input="$1"
    local target="$2"
    local tolerance="${3:-2}"  # Max distance for match

    local distance=$(levenshtein_distance "$input" "$target")

    if [[ $distance -le $tolerance ]]; then
        echo "true|$distance"
    else
        echo "false|$distance"
    fi
}

# Expand keywords to include common typos and variations
expand_keywords() {
    local keyword="$1"

    case "${keyword,,}" in
        # Mobile/PWA variations
        mobile)
            echo "mobile|mobil|moble|mobilr|movile"
            ;;
        responsive)
            echo "responsive|responsiv|resposive|respnsive|responsiveness"
            ;;
        pwa)
            echo "pwa|pwas|progessive|progressive"
            ;;

        # API variations
        api)
            echo "api|apis|apl|apii|endpoint"
            ;;
        rowsaffected)
            echo "rowsaffected|rows-affected|rows_affected|affectedrows|affected-rows|rowsAffected"
            ;;

        # Schema variations
        schema)
            echo "schema|schma|scema|scheme|schemas"
            ;;
        migration)
            echo "migration|migraton|migrate|migrations|migrating"
            ;;
        database)
            echo "database|databse|datbase|db|databases"
            ;;

        # Performance variations
        performance)
            echo "performance|performnce|perf|performace|speed"
            ;;
        optimize)
            echo "optimize|optimise|optimze|optimization|optimisation"
            ;;
        slow)
            echo "slow|sluggish|laggy|lagging|delayed"
            ;;

        # Security variations
        security)
            echo "security|secuity|secure|securities|safety"
            ;;
        vulnerability)
            echo "vulnerability|vulnrability|vuln|vulnerabilities|vulnerable"
            ;;
        injection)
            echo "injection|injecton|inject|injections"
            ;;

        # Accessibility variations
        accessibility)
            echo "accessibility|accessiblity|a11y|accessible|accessability"
            ;;
        wcag)
            echo "wcag|wgac|w3c|wcag2|wcag21"
            ;;
        aria)
            echo "aria|arria|arias|arial|aria-"
            ;;

        # Documentation variations
        documentation)
            echo "documentation|documention|docs|document|documenting"
            ;;
        readme)
            echo "readme|read-me|reademe|readme.md|README"
            ;;

        # Default - return original
        *)
            echo "$keyword"
            ;;
    esac
}

# Semantic keyword expansion (synonyms and related terms)
semantic_expand() {
    local keyword="$1"

    case "${keyword,,}" in
        # Performance synonyms
        fast)
            echo "fast|quick|rapid|speedy|swift"
            ;;
        slow)
            echo "slow|sluggish|laggy|delayed|latent"
            ;;
        optimize)
            echo "optimize|improve|enhance|boost|accelerate"
            ;;

        # Security synonyms
        secure)
            echo "secure|safe|protected|hardened|fortified"
            ;;
        vulnerability)
            echo "vulnerability|weakness|flaw|exposure|risk"
            ;;
        attack)
            echo "attack|exploit|breach|compromise|infiltration"
            ;;

        # Development synonyms
        create)
            echo "create|build|make|construct|develop"
            ;;
        fix)
            echo "fix|repair|patch|resolve|correct"
            ;;
        update)
            echo "update|modify|change|alter|edit"
            ;;

        # UI/UX synonyms
        layout)
            echo "layout|design|structure|arrangement|format"
            ;;
        responsive)
            echo "responsive|adaptive|flexible|fluid|elastic"
            ;;
        mobile)
            echo "mobile|phone|smartphone|cellular|portable"
            ;;

        *)
            echo "$keyword"
            ;;
    esac
}

# Apply fuzzy matching to keyword pattern
apply_fuzzy_to_pattern() {
    local pattern="$1"
    local expand_typos="${2:-true}"
    local expand_semantics="${3:-false}"

    local expanded_pattern=""
    local keywords=(${pattern//|/ })

    for keyword in "${keywords[@]}"; do
        local expanded="$keyword"

        # Add typo variations
        if [[ "$expand_typos" == "true" ]]; then
            local typo_expanded=$(expand_keywords "$keyword")
            if [[ "$typo_expanded" != "$keyword" ]]; then
                expanded="$typo_expanded"
            fi
        fi

        # Add semantic variations
        if [[ "$expand_semantics" == "true" ]]; then
            local semantic_expanded=$(semantic_expand "$keyword")
            if [[ "$semantic_expanded" != "$keyword" ]] && [[ "$semantic_expanded" != "$expanded" ]]; then
                expanded="${expanded}|${semantic_expanded}"
            fi
        fi

        if [[ -z "$expanded_pattern" ]]; then
            expanded_pattern="$expanded"
        else
            expanded_pattern="${expanded_pattern}|${expanded}"
        fi
    done

    echo "$expanded_pattern"
}

# Find closest matching keyword
find_closest_keyword() {
    local input="$1"
    local keywords="$2"
    local max_distance="${3:-3}"

    local best_match=""
    local best_distance=999

    local keyword_array=(${keywords//|/ })

    for keyword in "${keyword_array[@]}"; do
        local result=$(fuzzy_match "$input" "$keyword" "$max_distance")
        local is_match=$(echo "$result" | cut -d'|' -f1)
        local distance=$(echo "$result" | cut -d'|' -f2)

        if [[ "$is_match" == "true" ]] && [[ $distance -lt $best_distance ]]; then
            best_match="$keyword"
            best_distance=$distance
        fi
    done

    if [[ -n "$best_match" ]]; then
        echo "$best_match|$best_distance"
    else
        echo "|999"
    fi
}

# Export functions
export -f levenshtein_distance
export -f fuzzy_match
export -f expand_keywords
export -f semantic_expand
export -f apply_fuzzy_to_pattern
export -f find_closest_keyword

# Self-test when run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Fuzzy Matching Library Self-Test"
    echo "================================"

    # Test Levenshtein distance
    echo -n "Testing Levenshtein distance... "
    distance=$(levenshtein_distance "mobile" "mobil")
    if [[ $distance -eq 1 ]]; then
        echo "✅ PASS (distance: $distance)"
    else
        echo "❌ FAIL (expected 1, got $distance)"
    fi

    # Test fuzzy match
    echo -n "Testing fuzzy match... "
    result=$(fuzzy_match "securty" "security" 2)
    is_match=$(echo "$result" | cut -d'|' -f1)
    if [[ "$is_match" == "true" ]]; then
        echo "✅ PASS"
    else
        echo "❌ FAIL"
    fi

    # Test keyword expansion
    echo -n "Testing keyword expansion... "
    expanded=$(expand_keywords "mobile")
    if [[ "$expanded" == *"mobil"* ]]; then
        echo "✅ PASS"
    else
        echo "❌ FAIL"
    fi

    # Test semantic expansion
    echo -n "Testing semantic expansion... "
    expanded=$(semantic_expand "slow")
    if [[ "$expanded" == *"sluggish"* ]]; then
        echo "✅ PASS"
    else
        echo "❌ FAIL"
    fi

    # Test pattern expansion
    echo -n "Testing pattern expansion... "
    original="mobile|api|security"
    expanded=$(apply_fuzzy_to_pattern "$original" true false)
    if [[ "$expanded" == *"mobil"* ]] && [[ "$expanded" == *"secuity"* ]]; then
        echo "✅ PASS"
    else
        echo "❌ FAIL"
    fi

    # Test closest keyword
    echo -n "Testing closest keyword... "
    result=$(find_closest_keyword "performnce" "performance|security|mobile")
    match=$(echo "$result" | cut -d'|' -f1)
    if [[ "$match" == "performance" ]]; then
        echo "✅ PASS (matched: $match)"
    else
        echo "❌ FAIL"
    fi

    echo ""
    echo "Fuzzy matching library ready!"
fi