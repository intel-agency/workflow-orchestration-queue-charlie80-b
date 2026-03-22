#!/usr/bin/env bash
#
# verify-template-structure.sh
#
# Verifies that the template repository was properly cloned and the repository
# structure is correct. This script is designed to run in CI for ongoing
# verification of repository integrity.
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed
#
# Usage:
#   ./scripts/verify-template-structure.sh [--verbose]
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

# Verbose mode
VERBOSE=false
if [[ "${1:-}" == "--verbose" || "${1:-}" == "-v" ]]; then
    VERBOSE=true
fi

# Helper functions
log_pass() {
    echo -e "${GREEN}✓${NC} $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

log_fail() {
    echo -e "${RED}✗${NC} $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

log_warn() {
    echo -e "${YELLOW}!${NC} $1"
    WARN_COUNT=$((WARN_COUNT + 1))
}

log_info() {
    if $VERBOSE; then
        echo -e "${BLUE}ℹ${NC} $1"
    fi
}

log_section() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# =============================================================================
# STORY 1: Verify Git Repository Integrity
# =============================================================================
verify_git_integrity() {
    log_section "Story 1: Verify Git Repository Integrity"

    # 1.1 Verify .git directory exists
    if [[ -d ".git" ]]; then
        log_pass ".git directory exists"
    else
        log_fail ".git directory is missing"
    fi

    # 1.1 Verify remote origin is configured
    if git remote get-url origin &>/dev/null; then
        local remote_url
        remote_url=$(git remote get-url origin)
        log_pass "Remote origin is configured: $remote_url"
    else
        log_fail "Remote origin is not configured"
    fi

    # 1.2 Verify git history has commits
    local commit_count
    commit_count=$(git rev-list --count HEAD 2>/dev/null || echo "0")
    if [[ "$commit_count" -gt 0 ]]; then
        log_pass "Git history is intact ($commit_count commits)"
    else
        log_fail "Git history is empty (no commits found)"
    fi

    # 1.2 Verify branches are available
    local branch_count
    branch_count=$(git branch -a 2>/dev/null | wc -l)
    if [[ "$branch_count" -gt 0 ]]; then
        log_pass "Branches available ($branch_count branches)"
    else
        log_fail "No branches found"
    fi

    # Check current branch
    local current_branch
    current_branch=$(git branch --show-current)
    log_info "Current branch: $current_branch"
}

# =============================================================================
# STORY 2: Verify Repository Structure
# =============================================================================
verify_repository_structure() {
    log_section "Story 2: Verify Repository Structure"

    # 2.1 Verify all expected directories exist
    local required_dirs=(
        ".devcontainer"
        ".github"
        ".github/workflows"
        ".github/.devcontainer"
        ".opencode"
        ".opencode/agents"
        ".opencode/commands"
        "scripts"
        "local_ai_instruction_modules"
        "test"
        "plan_docs"
    )

    for dir in "${required_dirs[@]}"; do
        if [[ -d "$dir" ]]; then
            log_pass "Directory exists: $dir"
        else
            log_fail "Directory missing: $dir"
        fi
    done

    # 2.2 Verify critical files exist
    local critical_files=(
        "AGENTS.md"
        ".devcontainer/devcontainer.json"
        ".github/workflows/orchestrator-agent.yml"
        "opencode.json"
    )

    for file in "${critical_files[@]}"; do
        if [[ -f "$file" ]]; then
            log_pass "Critical file exists: $file"
        else
            log_fail "Critical file missing: $file"
        fi
    done
}

# =============================================================================
# STORY 3: Confirm Development Tooling
# =============================================================================
verify_development_tooling() {
    log_section "Story 3: Confirm Development Tooling"

    # 3.1 Verify devcontainer configuration
    local devcontainer_file=".devcontainer/devcontainer.json"

    if [[ -f "$devcontainer_file" ]]; then
        # Check for GHCR image reference
        if grep -q "ghcr.io" "$devcontainer_file"; then
            log_pass "DevContainer references GHCR image"
            local image
            image=$(grep -oP '"image":\s*"\K[^"]+' "$devcontainer_file" 2>/dev/null || echo "")
            if [[ -n "$image" ]]; then
                log_info "Image: $image"
            fi
        else
            log_fail "DevContainer does not reference GHCR image"
        fi

        # Check for port 4096 configuration
        if grep -q "4096" "$devcontainer_file"; then
            log_pass "Port 4096 configured for opencode server"
        else
            log_fail "Port 4096 not configured in devcontainer"
        fi

        # Check for postStartCommand
        if grep -q "postStartCommand" "$devcontainer_file"; then
            log_pass "postStartCommand configured in devcontainer"
        else
            log_warn "postStartCommand not configured in devcontainer"
        fi
    else
        log_fail "DevContainer configuration file not found"
    fi

    # 3.2 Verify required scripts exist
    local required_scripts=(
        "scripts/start-opencode-server.sh"
    )

    for script in "${required_scripts[@]}"; do
        if [[ -f "$script" ]]; then
            log_pass "Required script exists: $script"
            
            # Check if script is executable
            if [[ -x "$script" ]]; then
                log_info "Script is executable: $script"
            else
                log_warn "Script is not executable: $script"
            fi
        else
            log_fail "Required script missing: $script"
        fi
    done

    # Check for devcontainer orchestration script
    # Note: The template uses 'devcontainer-opencode.sh' instead of 'run-devcontainer-orchestrator.sh'
    local orchestration_scripts=(
        "scripts/devcontainer-opencode.sh"
        "scripts/run-devcontainer-orchestrator.sh"
    )

    local found_orchestration=false
    for script in "${orchestration_scripts[@]}"; do
        if [[ -f "$script" ]]; then
            log_pass "DevContainer orchestration script exists: $script"
            found_orchestration=true
            break
        fi
    done

    if ! $found_orchestration; then
        log_warn "No devcontainer orchestration script found (expected: devcontainer-opencode.sh or run-devcontainer-orchestrator.sh)"
    fi
}

# =============================================================================
# Additional Verification: Agent Configuration
# =============================================================================
verify_agent_configuration() {
    log_section "Additional: Verify Agent Configuration"

    # Check for orchestrator agent
    if [[ -f ".opencode/agents/orchestrator.md" ]]; then
        log_pass "Orchestrator agent definition exists"
    else
        log_fail "Orchestrator agent definition missing"
    fi

    # Check for MCP server configuration in opencode.json
    if [[ -f "opencode.json" ]]; then
        if grep -q "mcp" "opencode.json"; then
            log_pass "MCP servers configured in opencode.json"
            
            # Check for specific MCP servers
            if grep -q "sequential-thinking" "opencode.json"; then
                log_info "Sequential thinking MCP server configured"
            fi
            if grep -q "memory" "opencode.json"; then
                log_info "Memory MCP server configured"
            fi
        else
            log_warn "No MCP servers configured in opencode.json"
        fi
    fi

    # Check for workflow prompts directory
    if [[ -d ".github/workflows/prompts" ]]; then
        log_pass "Workflow prompts directory exists"
        
        if [[ -f ".github/workflows/prompts/orchestrator-agent-prompt.md" ]]; then
            log_pass "Orchestrator agent prompt template exists"
        else
            log_fail "Orchestrator agent prompt template missing"
        fi
    else
        log_fail "Workflow prompts directory missing"
    fi
}

# =============================================================================
# Summary
# =============================================================================
print_summary() {
    log_section "Verification Summary"

    local total=$((PASS_COUNT + FAIL_COUNT + WARN_COUNT))
    
    echo ""
    echo -e "  ${GREEN}Passed:${NC}   $PASS_COUNT"
    echo -e "  ${RED}Failed:${NC}   $FAIL_COUNT"
    echo -e "  ${YELLOW}Warnings:${NC} $WARN_COUNT"
    echo -e "  ${BLUE}Total:${NC}    $total"
    echo ""

    if [[ $FAIL_COUNT -eq 0 ]]; then
        echo -e "${GREEN}══════════════════════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}  ALL VERIFICATION CHECKS PASSED${NC}"
        echo -e "${GREEN}══════════════════════════════════════════════════════════════════════════${NC}"
        echo ""
        return 0
    else
        echo -e "${RED}══════════════════════════════════════════════════════════════════════════${NC}"
        echo -e "${RED}  VERIFICATION FAILED - $FAIL_COUNT check(s) did not pass${NC}"
        echo -e "${RED}══════════════════════════════════════════════════════════════════════════${NC}"
        echo ""
        return 1
    fi
}

# =============================================================================
# Main
# =============================================================================
main() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║        Template Repository Structure Verification                        ║${NC}"
    echo -e "${BLUE}║        Epic #6 - Phase 0, Task 0.1                                       ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
    
    # Get repository info
    local repo_root
    repo_root=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
    cd "$repo_root"
    
    log_info "Repository root: $(pwd)"
    log_info "Running verification at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    
    # Run all verification checks
    verify_git_integrity
    verify_repository_structure
    verify_development_tooling
    verify_agent_configuration
    
    # Print summary and exit with appropriate code
    print_summary
}

# Run main
main "$@"
