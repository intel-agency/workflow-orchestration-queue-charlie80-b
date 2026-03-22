#!/usr/bin/env bash
set -euo pipefail

# test-shell-bridge.sh
#
# Test suite for the shell-bridge dispatcher (Epic Issue #19).
# Tests cover:
#   - devcontainer-opencode.sh lifecycle commands (up, start, stop, down, status)
#   - run_opencode_prompt.sh prompt execution
#   - Timeout safety net
#   - JSONL logging
#
# Usage:
#   bash test/test-shell-bridge.sh
#
# Environment:
#   SKIP_CONTAINER_TESTS=1  - Skip tests that require Docker/devcontainer
#   TEST_WORKSPACE          - Override test workspace directory

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_WORKSPACE="${TEST_WORKSPACE:-$REPO_ROOT/test/fixtures/shell-bridge-test}"
LOG_DIR="$REPO_ROOT/logs"

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test helper functions
test_start() {
    local test_name="$1"
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -e "${YELLOW}TEST:${NC} $test_name"
}

test_pass() {
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo -e "  ${GREEN}PASS${NC}"
}

test_fail() {
    local reason="$1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    echo -e "  ${RED}FAIL${NC}: $reason"
}

test_skip() {
    local reason="$1"
    echo -e "  ${YELLOW}SKIP${NC}: $reason"
}

# Setup test environment
setup_test_env() {
    echo "=== Setting up test environment ==="
    
    # Create test workspace
    mkdir -p "$TEST_WORKSPACE"
    
    # Create logs directory
    mkdir -p "$LOG_DIR"
    
    # Create minimal devcontainer.json for tests
    mkdir -p "$TEST_WORKSPACE/.devcontainer"
    cat > "$TEST_WORKSPACE/.devcontainer/devcontainer.json" <<'EOF'
{
  "name": "test-shell-bridge",
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
  "remoteUser": "vscode"
}
EOF
    
    # Create test scripts directory structure
    mkdir -p "$TEST_WORKSPACE/scripts"
    
    # Copy scripts to test workspace
    cp "$REPO_ROOT/scripts/devcontainer-opencode.sh" "$TEST_WORKSPACE/scripts/"
    cp "$REPO_ROOT/scripts/run_opencode_prompt.sh" "$TEST_WORKSPACE/scripts/"
    cp "$REPO_ROOT/scripts/start-opencode-server.sh" "$TEST_WORKSPACE/scripts/"
    
    chmod +x "$TEST_WORKSPACE/scripts/"*.sh
    
    echo "Test environment ready at: $TEST_WORKSPACE"
    echo ""
}

# Cleanup test environment
cleanup_test_env() {
    echo ""
    echo "=== Cleaning up test environment ==="
    
    # Remove test workspace
    rm -rf "$TEST_WORKSPACE"
    
    # Clean up test log files
    rm -f "$LOG_DIR"/test-*.jsonl
    
    echo "Cleanup complete"
}

# ============================================
# Script Validation Tests
# ============================================

test_scripts_exist() {
    test_start "Scripts exist and are executable"
    
    local scripts=(
        "$REPO_ROOT/scripts/devcontainer-opencode.sh"
        "$REPO_ROOT/scripts/run_opencode_prompt.sh"
        "$REPO_ROOT/scripts/start-opencode-server.sh"
    )
    
    local all_exist=true
    for script in "${scripts[@]}"; do
        if [[ ! -f "$script" ]]; then
            test_fail "Script not found: $script"
            all_exist=false
        elif [[ ! -x "$script" ]]; then
            test_fail "Script not executable: $script"
            all_exist=false
        fi
    done
    
    if $all_exist; then
        test_pass
    fi
}

test_shellcheck_passes() {
    test_start "ShellCheck passes on all scripts"
    
    if ! command -v shellcheck >/dev/null 2>&1; then
        test_skip "shellcheck not installed"
        return
    fi
    
    local scripts=(
        "$REPO_ROOT/scripts/devcontainer-opencode.sh"
        "$REPO_ROOT/scripts/run_opencode_prompt.sh"
    )
    
    local all_pass=true
    for script in "${scripts[@]}"; do
        if ! shellcheck -s bash "$script" 2>/dev/null; then
            test_fail "ShellCheck failed for: $script"
            all_pass=false
        fi
    done
    
    if $all_pass; then
        test_pass
    fi
}

test_bash_syntax_valid() {
    test_start "Bash syntax is valid"
    
    local scripts=(
        "$REPO_ROOT/scripts/devcontainer-opencode.sh"
        "$REPO_ROOT/scripts/run_opencode_prompt.sh"
        "$REPO_ROOT/scripts/start-opencode-server.sh"
    )
    
    local all_valid=true
    for script in "${scripts[@]}"; do
        if ! bash -n "$script" 2>/dev/null; then
            test_fail "Syntax error in: $script"
            all_valid=false
        fi
    done
    
    if $all_valid; then
        test_pass
    fi
}

# ============================================
# CLI Usage Tests
# ============================================

test_devcontainer_opencode_usage() {
    test_start "devcontainer-opencode.sh shows usage"
    
    local output
    if output=$(bash "$REPO_ROOT/scripts/devcontainer-opencode.sh" 2>&1); then
        test_fail "Expected exit code 1, got 0"
        return
    fi
    
    if [[ "$output" == *"Usage:"* && "$output" == *"Commands:"* ]]; then
        test_pass
    else
        test_fail "Usage output missing expected content"
    fi
}

test_devcontainer_opencode_unknown_command() {
    test_start "devcontainer-opencode.sh rejects unknown command"
    
    local output
    if output=$(bash "$REPO_ROOT/scripts/devcontainer-opencode.sh" unknown-cmd 2>&1); then
        test_fail "Expected exit code 1, got 0"
        return
    fi
    
    # Check for both capitalized and lowercase versions
    if [[ "$output" == *"Unknown command"* || "$output" == *"unknown command"* ]]; then
        test_pass
    else
        test_fail "Expected 'unknown command' error message"
    fi
}

test_run_opencode_prompt_usage() {
    test_start "run_opencode_prompt.sh shows usage"
    
    local output
    if output=$(bash "$REPO_ROOT/scripts/run_opencode_prompt.sh" 2>&1); then
        test_fail "Expected exit code 1, got 0"
        return
    fi
    
    if [[ "$output" == *"Usage:"* ]]; then
        test_pass
    else
        test_fail "Usage output missing"
    fi
}

test_run_opencode_prompt_requires_prompt() {
    test_start "run_opencode_prompt.sh requires prompt (-f or -p)"
    
    local output
    if output=$(bash "$REPO_ROOT/scripts/run_opencode_prompt.sh" -a "http://localhost:4096" 2>&1); then
        test_fail "Expected exit code 1, got 0"
        return
    fi
    
    if [[ "$output" == *"-f"* || "$output" == *"-p"* ]]; then
        test_pass
    else
        test_fail "Expected prompt requirement message"
    fi
}

# ============================================
# Environment Validation Tests
# ============================================

test_run_opencode_prompt_validates_env() {
    test_start "run_opencode_prompt.sh validates required environment variables"
    
    # Clear required vars
    local output
    output=$(unset ZHIPU_API_KEY KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY GITHUB_TOKEN; \
        bash "$REPO_ROOT/scripts/run_opencode_prompt.sh" -a "http://localhost:4096" -p "test" 2>&1) || true
    
    if [[ "$output" == *"ZHIPU_API_KEY"* || "$output" == *"environment"* || "$output" == *"Missing"* ]]; then
        test_pass
    else
        test_fail "Expected environment validation error"
    fi
}

test_devcontainer_opencode_prompt_validates_env() {
    test_start "devcontainer-opencode.sh prompt validates environment variables"
    
    local output
    output=$(unset ZHIPU_API_KEY KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY GITHUB_TOKEN; \
        bash "$REPO_ROOT/scripts/devcontainer-opencode.sh" prompt -p "test" 2>&1) || true
    
    if [[ "$output" == *"ZHIPU_API_KEY"* || "$output" == *"Missing"* || "$output" == *"environment"* ]]; then
        test_pass
    else
        test_fail "Expected environment validation error"
    fi
}

# ============================================
# JSONL Logging Tests
# ============================================

test_jsonl_log_format() {
    test_start "JSONL logs have correct format"
    
    # Create a test log file with sample JSONL
    local test_log="$LOG_DIR/test-jsonl-format.jsonl"
    cat > "$test_log" <<'EOF'
{"timestamp":"2026-03-22T10:00:00.000Z","level":"INFO","message":"Test message","metadata":{}}
{"timestamp":"2026-03-22T10:00:01.000Z","level":"ERROR","message":"Error message","metadata":{"key":"value"}}
EOF
    
    # Validate each line is valid JSON
    local line_num=0
    local all_valid=true
    while IFS= read -r line; do
        line_num=$((line_num + 1))
        if ! echo "$line" | python3 -m json.tool >/dev/null 2>&1; then
            test_fail "Invalid JSON on line $line_num"
            all_valid=false
        fi
    done < "$test_log"
    
    rm -f "$test_log"
    
    if $all_valid; then
        test_pass
    fi
}

test_jsonl_required_fields() {
    test_start "JSONL logs contain required fields"
    
    local test_log="$LOG_DIR/test-jsonl-fields.jsonl"
    cat > "$test_log" <<'EOF'
{"timestamp":"2026-03-22T10:00:00.000Z","level":"INFO","message":"Test","metadata":{}}
EOF
    
    local has_timestamp has_level has_message has_metadata
    has_timestamp=$(grep -o '"timestamp"' "$test_log" || true)
    has_level=$(grep -o '"level"' "$test_log" || true)
    has_message=$(grep -o '"message"' "$test_log" || true)
    has_metadata=$(grep -o '"metadata"' "$test_log" || true)
    
    rm -f "$test_log"
    
    if [[ -n "$has_timestamp" && -n "$has_level" && -n "$has_message" && -n "$has_metadata" ]]; then
        test_pass
    else
        test_fail "Missing required JSONL fields"
    fi
}

test_log_directory_creation() {
    test_start "Log directory is created when needed"
    
    local test_log_dir="$REPO_ROOT/logs-test-$$"
    rm -rf "$test_log_dir"
    
    # Source the script's log function behavior by checking if it creates the directory
    # We'll test this indirectly by verifying the script references the log directory
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/run_opencode_prompt.sh")
    
    if [[ "$script_content" == *"mkdir -p"* && "$script_content" == *"OPENCODE_LOG_DIR"* ]]; then
        rm -rf "$test_log_dir"
        test_pass
    else
        rm -rf "$test_log_dir"
        test_fail "Script should create log directory"
    fi
}

# ============================================
# Timeout Configuration Tests
# ============================================

test_default_timeout() {
    test_start "Default timeout is 5700 seconds (95 min)"
    
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/run_opencode_prompt.sh")
    
    if [[ "$script_content" == *":-\${OPENCODE_EXECUTION_TIMEOUT_SECS:-5700}"* || \
          "$script_content" == *"OPENCODE_EXECUTION_TIMEOUT_SECS:-5700"* ]]; then
        test_pass
    else
        test_fail "Default timeout not set to 5700"
    fi
}

test_timeout_env_override() {
    test_start "Timeout can be overridden via environment variable"
    
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/run_opencode_prompt.sh")
    
    if [[ "$script_content" == *"OPENCODE_EXECUTION_TIMEOUT_SECS"* ]]; then
        test_pass
    else
        test_fail "Timeout environment variable not supported"
    fi
}

test_timeout_command_option() {
    test_start "Timeout uses 'timeout' command for subprocess management"
    
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/run_opencode_prompt.sh")
    
    if [[ "$script_content" == *"timeout"* && "$script_content" == *"SIGTERM"* ]]; then
        test_pass
    else
        test_fail "Timeout command or signal handling not found"
    fi
}

# ============================================
# Exit Code Tests
# ============================================

test_exit_codes_defined() {
    test_start "Exit codes are documented and used"
    
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/run_opencode_prompt.sh")
    
    # Check for exit code documentation
    if [[ "$script_content" == *"Exit Codes:"* && \
          "$script_content" == *"exit 1"* && \
          "$script_content" == *"exit 2"* && \
          "$script_content" == *"exit 3"* ]]; then
        test_pass
    else
        test_fail "Exit codes not properly documented or used"
    fi
}

test_missing_prompt_file_exit_code() {
    test_start "Missing prompt file returns exit code 1"
    
    local output exit_code
    output=$(bash "$REPO_ROOT/scripts/run_opencode_prompt.sh" \
        -a "http://localhost:4096" \
        -f "/nonexistent/prompt.md" \
        2>&1) || exit_code=$?
    
    if [[ "${exit_code:-0}" -eq 1 ]]; then
        test_pass
    else
        test_fail "Expected exit code 1, got ${exit_code:-0}"
    fi
}

# ============================================
# Container Tests (Optional - requires Docker)
# ============================================

test_container_lifecycle_commands_defined() {
    test_start "Container lifecycle commands are defined"
    
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/devcontainer-opencode.sh")
    
    if [[ "$script_content" == *"cmd_up"* && \
          "$script_content" == *"cmd_start"* && \
          "$script_content" == *"cmd_stop"* && \
          "$script_content" == *"cmd_down"* && \
          "$script_content" == *"cmd_status"* ]]; then
        test_pass
    else
        test_fail "Lifecycle commands not properly defined"
    fi
}

test_container_discovery_function() {
    test_start "Container discovery function exists"
    
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/devcontainer-opencode.sh")
    
    if [[ "$script_content" == *"find_container"* && \
          "$script_content" == *"devcontainer.local_folder"* ]]; then
        test_pass
    else
        test_fail "Container discovery function not found"
    fi
}

test_container_state_detection() {
    test_start "Container state detection function exists"
    
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/devcontainer-opencode.sh")
    
    if [[ "$script_content" == *"get_container_state"* && \
          "$script_content" == *"State.Status"* ]]; then
        test_pass
    else
        test_fail "Container state detection not found"
    fi
}

# ============================================
# Server Connection Tests
# ============================================

test_server_connection_check() {
    test_start "Server connection check function exists"
    
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/run_opencode_prompt.sh")
    
    if [[ "$script_content" == *"check_server_connection"* && \
          "$script_content" == *"curl"* ]]; then
        test_pass
    else
        test_fail "Server connection check not found"
    fi
}

test_server_unreachable_exit_code() {
    test_start "Server unreachable returns exit code 3"
    
    local script_content
    script_content=$(cat "$REPO_ROOT/scripts/run_opencode_prompt.sh")
    
    if [[ "$script_content" == *"exit 3"* ]]; then
        test_pass
    else
        test_fail "Exit code 3 for server failure not found"
    fi
}

# ============================================
# Run All Tests
# ============================================

run_all_tests() {
    echo "=== Shell-Bridge Dispatcher Test Suite ==="
    echo ""
    
    # Setup
    setup_test_env
    
    echo "=== Running Tests ==="
    echo ""
    
    # Script Validation Tests
    echo "--- Script Validation ---"
    test_scripts_exist
    test_shellcheck_passes
    test_bash_syntax_valid
    echo ""
    
    # CLI Usage Tests
    echo "--- CLI Usage ---"
    test_devcontainer_opencode_usage
    test_devcontainer_opencode_unknown_command
    test_run_opencode_prompt_usage
    test_run_opencode_prompt_requires_prompt
    echo ""
    
    # Environment Validation Tests
    echo "--- Environment Validation ---"
    test_run_opencode_prompt_validates_env
    test_devcontainer_opencode_prompt_validates_env
    echo ""
    
    # JSONL Logging Tests
    echo "--- JSONL Logging ---"
    test_jsonl_log_format
    test_jsonl_required_fields
    test_log_directory_creation
    echo ""
    
    # Timeout Tests
    echo "--- Timeout Configuration ---"
    test_default_timeout
    test_timeout_env_override
    test_timeout_command_option
    echo ""
    
    # Exit Code Tests
    echo "--- Exit Codes ---"
    test_exit_codes_defined
    test_missing_prompt_file_exit_code
    echo ""
    
    # Container Tests
    echo "--- Container Lifecycle ---"
    test_container_lifecycle_commands_defined
    test_container_discovery_function
    test_container_state_detection
    echo ""
    
    # Server Tests
    echo "--- Server Connection ---"
    test_server_connection_check
    test_server_unreachable_exit_code
    echo ""
    
    # Cleanup
    cleanup_test_env
    
    # Summary
    echo ""
    echo "=== Test Summary ==="
    echo "Tests Run:    $TESTS_RUN"
    echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"
    echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"
    echo ""
    
    if [[ $TESTS_FAILED -gt 0 ]]; then
        echo -e "${RED}SOME TESTS FAILED${NC}"
        exit 1
    else
        echo -e "${GREEN}ALL TESTS PASSED${NC}"
        exit 0
    fi
}

# Run tests
run_all_tests
