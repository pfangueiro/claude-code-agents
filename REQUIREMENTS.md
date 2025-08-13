# System Requirements & Dependencies

## 🖥️ Operating System Support
- ✅ macOS (10.15+)
- ✅ Linux (Ubuntu 20.04+, Debian 10+, RHEL 8+)
- ⚠️ Windows (WSL2 required)

## 📦 Required Dependencies

### Core Requirements
| Dependency | Version | Purpose | Install Command |
|------------|---------|---------|----------------|
| **git** | 2.25+ | Version control | Pre-installed on most systems |
| **bash** | 4.0+ | Script execution | Pre-installed on Unix systems |

### Recommended Dependencies
| Dependency | Version | Purpose | Install Command |
|------------|---------|---------|----------------|
| **jq** | 1.6+ | JSON processing in tracking | `brew install jq` (macOS)<br>`apt-get install jq` (Ubuntu) |
| **bc** | 1.07+ | Cost calculations | `brew install bc` (macOS)<br>`apt-get install bc` (Ubuntu) |
| **uuidgen** | Any | Unique task IDs | `brew install ossp-uuid` (macOS)<br>`apt-get install uuid-runtime` (Ubuntu) |

### Optional Dependencies
| Dependency | Version | Purpose | Install Command |
|------------|---------|---------|----------------|
| **gh** | 2.0+ | GitHub issue tracking | `brew install gh` (macOS)<br>`curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \| sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg` |
| **curl** | 7.68+ | API interactions | Pre-installed on most systems |
| **date** | GNU | Timestamp generation | Pre-installed (use `gdate` on macOS if needed) |

## 🔧 Installation Commands

### macOS (Homebrew)
```bash
# Install all recommended dependencies
brew install jq bc ossp-uuid

# Optional: GitHub CLI
brew install gh
```

### Ubuntu/Debian
```bash
# Update package list
sudo apt-get update

# Install recommended dependencies
sudo apt-get install -y jq bc uuid-runtime

# Optional: GitHub CLI
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh
```

### RHEL/CentOS/Fedora
```bash
# Install EPEL repository
sudo yum install -y epel-release

# Install dependencies
sudo yum install -y jq bc uuid

# Optional: GitHub CLI
sudo dnf install -y gh
```

### Windows (WSL2)
```bash
# First, install WSL2
wsl --install

# Then follow Ubuntu instructions above
```

## 🐳 Docker Alternative

If you prefer containerized execution:

```dockerfile
FROM ubuntu:22.04

# Install all dependencies
RUN apt-get update && apt-get install -y \
    git \
    jq \
    bc \
    uuid-runtime \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Optional: Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt update \
    && apt install gh -y

# Copy agents
COPY .claude /root/.claude

WORKDIR /workspace
```

## ✅ Dependency Check Script

Run this to verify your system:

```bash
#!/bin/bash

echo "Checking system dependencies..."
echo "================================"

# Required
check_dep() {
    if command -v $1 &> /dev/null; then
        echo "✅ $1: $(command -v $1)"
    else
        echo "❌ $1: NOT FOUND - $2"
        return 1
    fi
}

# Check required
echo -e "\nRequired Dependencies:"
check_dep "git" "Required for version control"
check_dep "bash" "Required for script execution"

# Check recommended
echo -e "\nRecommended Dependencies:"
check_dep "jq" "Install with: brew install jq (macOS) or apt-get install jq (Linux)"
check_dep "bc" "Install with: brew install bc (macOS) or apt-get install bc (Linux)"
check_dep "uuidgen" "Install with: brew install ossp-uuid (macOS) or apt-get install uuid-runtime (Linux)" || check_dep "uuid" "Alternative to uuidgen"

# Check optional
echo -e "\nOptional Dependencies:"
check_dep "gh" "Install with: brew install gh (for GitHub integration)"
check_dep "curl" "Usually pre-installed"

echo -e "\n================================"
echo "System check complete!"
```

## 🔄 Fallback Mechanisms

The system includes fallbacks for missing dependencies:

### jq not available
- Tracking will use basic text parsing
- JSON logs may be malformed
- Dashboard will show limited information

### bc not available
- Cost calculations will not work
- Token usage still tracked
- Dashboard shows tokens but not costs

### uuidgen not available
- Falls back to timestamp-based IDs
- Format: `task-$(date +%s)-$$`
- Still unique but less random

### gh not available
- GitHub integration disabled
- Local tracking continues normally
- Can be enabled later when installed

## 📋 Verification

After installing dependencies, run:

```bash
# Test the installation
cd claude-code-agents
./install.sh --check-deps

# Or manually verify
.claude/scripts/setup-tracking.sh
```

## 🆘 Troubleshooting

### Issue: "command not found" errors
**Solution:** Ensure PATH includes `/usr/local/bin` and `/usr/bin`

### Issue: Permission denied on scripts
**Solution:** Run `chmod +x .claude/scripts/*.sh .claude/hooks/*.sh`

### Issue: GitHub CLI authentication failed
**Solution:** Run `gh auth login` and follow prompts

### Issue: Cost calculations showing 0
**Solution:** Install `bc` package for floating-point math

---

*Keep this document updated as requirements change*