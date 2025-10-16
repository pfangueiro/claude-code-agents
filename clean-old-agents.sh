#!/bin/bash

# Clean up old agent files before fresh installation

echo "🧹 Cleaning up old agent files..."

# Old agent files from v1.0
OLD_AGENTS=(
    "architect.md"
    "connector.md"
    "documenter.md"
    "guardian.md"
    "accessibility.md"
    "api-reliability.md"
    "documentation.md"
    "mobile-ux.md"
    "performance.md"
    "schema-guardian.md"
    "security.md"
)

# Remove old agents if they exist
for agent in "${OLD_AGENTS[@]}"; do
    if [ -f ".claude/agents/${agent}" ]; then
        rm ".claude/agents/${agent}"
        echo "  ✓ Removed old ${agent}"
    fi
done

echo "✅ Cleanup complete. You can now run the installer."