#!/usr/bin/env bash
#
# test-template-verification.sh
#
# Tests the verify-template-structure.sh script to ensure it works correctly
# and can be run in CI for ongoing verification.
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERIFY_SCRIPT="$ROOT_DIR/scripts/verify-template-structure.sh"

echo "Testing template verification script..."

# Test 1: Script exists and is executable
echo -n "  Test 1: Script exists... "
if [[ -f "$VERIFY_SCRIPT" ]]; then
    echo -e "${GREEN}PASS${NC}"
else
    echo -e "${RED}FAIL${NC}"
    echo "    Script not found at: $VERIFY_SCRIPT"
    exit 1
fi

# Test 2: Script is executable
echo -n "  Test 2: Script is executable... "
if [[ -x "$VERIFY_SCRIPT" ]]; then
    echo -e "${GREEN}PASS${NC}"
else
    echo -e "${RED}FAIL${NC}"
    echo "    Script is not executable"
    exit 1
fi

# Test 3: Script runs successfully (exit code 0)
echo -n "  Test 3: Script runs and exits 0... "
cd "$ROOT_DIR"
if "$VERIFY_SCRIPT" >/dev/null 2>&1; then
    echo -e "${GREEN}PASS${NC}"
else
    exit_code=$?
    echo -e "${RED}FAIL${NC}"
    echo "    Script exited with code: $exit_code"
    # Run again to show output for debugging
    "$VERIFY_SCRIPT" --verbose
    exit 1
fi

# Test 4: Script produces expected output sections
echo -n "  Test 4: Script produces expected output... "
output=$("$VERIFY_SCRIPT" 2>&1)
if echo "$output" | grep -q "Story 1: Verify Git Repository Integrity" && \
   echo "$output" | grep -q "Story 2: Verify Repository Structure" && \
   echo "$output" | grep -q "Story 3: Confirm Development Tooling" && \
   echo "$output" | grep -q "Verification Summary" && \
   echo "$output" | grep -q "ALL VERIFICATION CHECKS PASSED"; then
    echo -e "${GREEN}PASS${NC}"
else
    echo -e "${RED}FAIL${NC}"
    echo "    Missing expected output sections"
    echo "$output"
    exit 1
fi

# Test 5: Verbose mode works
echo -n "  Test 5: Verbose mode works... "
verbose_output=$("$VERIFY_SCRIPT" --verbose 2>&1)
if echo "$verbose_output" | grep -q "Repository root:"; then
    echo -e "${GREEN}PASS${NC}"
else
    echo -e "${RED}FAIL${NC}"
    echo "    Verbose mode not producing expected output"
    exit 1
fi

echo ""
echo -e "${GREEN}All template verification tests passed!${NC}"
exit 0
