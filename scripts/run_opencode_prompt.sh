#!/usr/bin/env bash
set -euo pipefail

# run_opencode_prompt.sh
#
# Execute prompts via the opencode server with timeout safety and JSONL logging.
# Designed to run inside the devcontainer.
#
# Usage:
#   run_opencode_prompt.sh -a <server-url> -f <prompt-file>
#   run_opencode_prompt.sh -a <server-url> -p <inline-prompt>
#
# Options:
#   -a <url>      opencode server URL (required, env: OPENCODE_SERVER_URL)
#   -f <file>     prompt file path (required, or use -p)
#   -p <prompt>   inline prompt string (required, or use -f)
#   -t <secs>     execution timeout in seconds (env: OPENCODE_EXECUTION_TIMEOUT_SECS, default: 5700)
#   -l <dir>      log directory for JSONL output (env: OPENCODE_LOG_DIR, default: ./logs)
#   -i <id>       execution ID for logging (env: OPENCODE_EXECUTION_ID, default: auto-generated)
#   -s <id>       Sentinel ID for logging (env: SENTINEL_ID, default: none)
#   -T <id>       Task ID for logging (env: TASK_ID, default: none)
#
# Environment Variables:
#   Required for prompt execution:
#     ZHIPU_API_KEY              - ZhipuAI API key
#     KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY - Kimi/Moonshot API key
#     GITHUB_TOKEN               - GitHub token for API access
#
#   Optional:
#     OPENCODE_EXECUTION_TIMEOUT_SECS - Timeout in seconds (default: 5700)
#     OPENCODE_LOG_DIR           - Directory for JSONL logs (default: ./logs)
#     OPENCODE_EXECUTION_ID      - Unique execution identifier
#     SENTINEL_ID                - Sentinel orchestrator identifier
#     TASK_ID                    - Task identifier for logging
#     GITHUB_PERSONAL_ACCESS_TOKEN - PAT for GitHub MCP server
#     GH_ORCHESTRATION_AGENT_TOKEN - Token for gh CLI
#
# Exit Codes:
#   0 - Success
#   1 - General error (missing args, validation failure)
#   2 - Timeout exceeded
#   3 - Server connection failure
#   124 - Timeout command exit (process killed by SIGTERM)

# Default configuration
OPENCODE_SERVER_URL="${OPENCODE_SERVER_URL:-http://127.0.0.1:4096}"
OPENCODE_EXECUTION_TIMEOUT_SECS="${OPENCODE_EXECUTION_TIMEOUT_SECS:-5700}"
OPENCODE_LOG_DIR="${OPENCODE_LOG_DIR:-./logs}"
OPENCODE_EXECUTION_ID="${OPENCODE_EXECUTION_ID:-}"
SENTINEL_ID="${SENTINEL_ID:-}"
TASK_ID="${TASK_ID:-}"
PROMPT_FILE=""
PROMPT_STRING=""

# Timing
SCRIPT_START_TIME="${EPOCHREALTIME:-$(date +%s.%N)}"

# Log file path (set after parsing args)
LOG_FILE=""

usage() {
    cat >&2 <<'EOF'
Usage: run_opencode_prompt.sh -a <server-url> (-f <prompt-file> | -p <inline-prompt>)

Execute prompts via the opencode server with timeout safety and JSONL logging.

Required:
  -a <url>      opencode server URL (env: OPENCODE_SERVER_URL)
  -f <file>     prompt file path (required, or use -p)
  -p <prompt>   inline prompt string (required, or use -f)

Optional:
  -t <secs>     execution timeout (env: OPENCODE_EXECUTION_TIMEOUT_SECS, default: 5700)
  -l <dir>      log directory (env: OPENCODE_LOG_DIR, default: ./logs)
  -i <id>       execution ID (env: OPENCODE_EXECUTION_ID)
  -s <id>       Sentinel ID (env: SENTINEL_ID)
  -T <id>       Task ID (env: TASK_ID)

Required Environment:
  ZHIPU_API_KEY, KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY, GITHUB_TOKEN

Exit Codes:
  0   Success
  1   General error
  2   Timeout exceeded
  3   Server connection failure
  124 Timeout signal received
EOF
    exit 1
}

# Generate a unique execution ID if not provided
generate_execution_id() {
    local timestamp
    timestamp="$(date +%Y%m%d_%H%M%S)"
    local random_suffix
    random_suffix="$(head /dev/urandom | tr -dc 'a-z0-9' | head -c 6)"
    echo "exec_${timestamp}_${random_suffix}"
}

# JSONL logging function
# Arguments: level message [metadata_json]
log_jsonl() {
    local level="$1"
    local message="$2"
    local metadata="${3:-{}}"
    local timestamp
    
    # ISO 8601 timestamp with milliseconds
    timestamp="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
    
    # Build the JSONL entry
    local entry
    entry=$(cat <<EOF
{"timestamp":"${timestamp}","level":"${level}","message":"${message}","metadata":${metadata}}
EOF
)
    
    # Write to log file if set
    if [[ -n "$LOG_FILE" ]]; then
        echo "$entry" >> "$LOG_FILE"
    fi
    
    # Also output to stderr for visibility (stdout is reserved for opencode output)
    echo "$entry" >&2
}

# Build metadata JSON for logging
build_metadata() {
    local pairs=()
    
    if [[ -n "$OPENCODE_EXECUTION_ID" ]]; then
        pairs+=("\"executionId\":\"$OPENCODE_EXECUTION_ID\"")
    fi
    
    if [[ -n "$SENTINEL_ID" ]]; then
        pairs+=("\"sentinelId\":\"$SENTINEL_ID\"")
    fi
    
    if [[ -n "$TASK_ID" ]]; then
        pairs+=("\"taskId\":\"$TASK_ID\"")
    fi
    
    if [[ -n "$PROMPT_FILE" ]]; then
        pairs+=("\"promptFile\":\"$PROMPT_FILE\"")
    fi
    
    if [[ -n "$OPENCODE_SERVER_URL" ]]; then
        pairs+=("\"serverUrl\":\"$OPENCODE_SERVER_URL\"")
    fi
    
    # Join pairs with commas
    local result
    result=$(IFS=,; echo "${pairs[*]}")
    echo "{$result}"
}

# Calculate elapsed time in seconds
get_elapsed_time() {
    local end_time
    end_time="${EPOCHREALTIME:-$(date +%s.%N)}"
    echo "$end_time - $SCRIPT_START_TIME" | bc
}

# Validate required environment variables
validate_environment() {
    local missing=()
    
    for var in ZHIPU_API_KEY KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY GITHUB_TOKEN; do
        if [[ -z "${!var:-}" ]]; then
            missing+=("$var")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        local metadata
        metadata="{\"missingVars\":[\"$(IFS='","'; echo "${missing[*]}")\"]}"
        log_jsonl "ERROR" "Missing required environment variables" "$metadata"
        echo "ERROR: Missing required environment variables: ${missing[*]}" >&2
        exit 1
    fi
    
    log_jsonl "DEBUG" "Environment validation passed" "{}"
}

# Check if the opencode server is reachable
check_server_connection() {
    local max_retries=3
    local retry_delay=2
    local retry=0
    
    while [[ $retry -lt $max_retries ]]; do
        if curl -s -o /dev/null --connect-timeout 5 "$OPENCODE_SERVER_URL/"; then
            log_jsonl "DEBUG" "Server connection established" "{\"serverUrl\":\"$OPENCODE_SERVER_URL\"}"
            return 0
        fi
        
        retry=$((retry + 1))
        if [[ $retry -lt $max_retries ]]; then
            log_jsonl "WARN" "Server connection failed, retrying" "{\"attempt\":$retry,\"maxRetries\":$max_retries,\"serverUrl\":\"$OPENCODE_SERVER_URL\"}"
            sleep "$retry_delay"
        fi
    done
    
    log_jsonl "ERROR" "Failed to connect to opencode server" "{\"serverUrl\":\"$OPENCODE_SERVER_URL\",\"attempts\":$max_retries}"
    return 1
}

# Clean up orphaned processes
cleanup_orphans() {
    local pids_file="/tmp/opencode-exec-pids-${OPENCODE_EXECUTION_ID}.txt"
    
    if [[ -f "$pids_file" ]]; then
        while IFS= read -r pid; do
            if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
                log_jsonl "WARN" "Cleaning up orphaned process" "{\"pid\":$pid}"
                kill -9 "$pid" 2>/dev/null || true
            fi
        done < "$pids_file"
        rm -f "$pids_file"
    fi
}

# Handle timeout escalation
handle_timeout() {
    local pid="$1"
    local signal="${2:-TERM}"
    
    log_jsonl "WARN" "Process timeout, sending signal" "{\"pid\":$pid,\"signal\":\"$signal\"}"
    
    if [[ "$signal" == "TERM" ]]; then
        kill -TERM "$pid" 2>/dev/null || true
        # Give process 10 seconds to terminate gracefully
        sleep 10
        if kill -0 "$pid" 2>/dev/null; then
            log_jsonl "WARN" "Process did not terminate gracefully, escalating to SIGKILL" "{\"pid\":$pid}"
            kill -KILL "$pid" 2>/dev/null || true
        fi
    else
        kill -KILL "$pid" 2>/dev/null || true
    fi
}

# Parse command line arguments
parse_args() {
    while getopts ":a:f:p:t:l:i:s:T:" opt; do
        case $opt in
            a) OPENCODE_SERVER_URL="$OPTARG" ;;
            f) PROMPT_FILE="$OPTARG" ;;
            p) PROMPT_STRING="$OPTARG" ;;
            t) OPENCODE_EXECUTION_TIMEOUT_SECS="$OPTARG" ;;
            l) OPENCODE_LOG_DIR="$OPTARG" ;;
            i) OPENCODE_EXECUTION_ID="$OPTARG" ;;
            s) SENTINEL_ID="$OPTARG" ;;
            T) TASK_ID="$OPTARG" ;;
            *) usage ;;
        esac
    done
    
    # Validate required arguments
    if [[ -z "$PROMPT_FILE" && -z "$PROMPT_STRING" ]]; then
        echo "ERROR: Either -f <prompt-file> or -p <prompt> is required" >&2
        usage
    fi
    
    # Generate execution ID if not provided
    if [[ -z "$OPENCODE_EXECUTION_ID" ]]; then
        OPENCODE_EXECUTION_ID="$(generate_execution_id)"
    fi
}

# Setup logging infrastructure
setup_logging() {
    # Create log directory
    mkdir -p "$OPENCODE_LOG_DIR"
    
    # Create timestamped log file
    local timestamp
    timestamp="$(date +%Y%m%d_%H%M%S)"
    LOG_FILE="${OPENCODE_LOG_DIR}/opencode-${OPENCODE_EXECUTION_ID}-${timestamp}.jsonl"
    
    # Initialize log file with header
    log_jsonl "INFO" "Execution started" "$(build_metadata)"
}

# Main execution
main() {
    parse_args "$@"
    setup_logging
    validate_environment
    
    # Check server connection
    if ! check_server_connection; then
        exit 3
    fi
    
    # Build prompt argument
    local prompt_arg
    if [[ -n "$PROMPT_STRING" ]]; then
        prompt_arg="-p"
        PROMPT_FILE="<inline>"
    else
        # Validate prompt file exists
        if [[ ! -f "$PROMPT_FILE" ]]; then
            log_jsonl "ERROR" "Prompt file not found" "{\"promptFile\":\"$PROMPT_FILE\"}"
            echo "ERROR: Prompt file not found: $PROMPT_FILE" >&2
            exit 1
        fi
        prompt_arg="-f"
    fi
    
    # Export tokens for opencode server
    export ZHIPU_API_KEY
    export KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY
    export GITHUB_TOKEN
    export GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:-$GITHUB_TOKEN}"
    export GH_ORCHESTRATION_AGENT_TOKEN="${GH_ORCHESTRATION_AGENT_TOKEN:-}"
    
    # Prefer cross-repo PAT for gh CLI
    if [[ -n "${GH_ORCHESTRATION_AGENT_TOKEN:-}" ]]; then
        export GH_TOKEN="$GH_ORCHESTRATION_AGENT_TOKEN"
    fi
    
    # Record execution start
    log_jsonl "INFO" "Starting opencode execution" "{\"timeoutSecs\":$OPENCODE_EXECUTION_TIMEOUT_SECS,\"promptSource\":\"$PROMPT_FILE\"}"
    
    # Execute with timeout
    local exit_code=0
    local opencode_pid
    
    # Create a temporary file to capture output
    local output_file
    output_file="$(mktemp)"
    trap "rm -f '$output_file'" EXIT
    
    # Track process for cleanup
    local pids_file="/tmp/opencode-exec-pids-${OPENCODE_EXECUTION_ID}.txt"
    
    if [[ -n "$PROMPT_STRING" ]]; then
        # Run with timeout, capturing output for JSONL logging
        timeout --signal=TERM --kill-after=10 "$OPENCODE_EXECUTION_TIMEOUT_SECS" \
            opencode run --attach "$OPENCODE_SERVER_URL" \
                --model zai-coding-plan/glm-5 \
                --agent Orchestrator \
                $prompt_arg "$PROMPT_STRING" \
                2>&1 | tee "$output_file" &
    else
        timeout --signal=TERM --kill-after=10 "$OPENCODE_EXECUTION_TIMEOUT_SECS" \
            opencode run --attach "$OPENCODE_SERVER_URL" \
                --model zai-coding-plan/glm-5 \
                --agent Orchestrator \
                $prompt_arg "$PROMPT_FILE" \
                2>&1 | tee "$output_file" &
    fi
    
    opencode_pid=$!
    echo "$opencode_pid" > "$pids_file"
    
    # Wait for process and capture exit code
    wait "$opencode_pid" 2>/dev/null || exit_code=$?
    
    # Clean up pid tracking
    rm -f "$pids_file"
    
    # Calculate elapsed time
    local elapsed
    elapsed=$(get_elapsed_time)
    
    # Process output for JSONL logging
    if [[ -s "$output_file" ]]; then
        while IFS= read -r line; do
            # Determine log level based on content
            local level="INFO"
            if [[ "$line" =~ ^[Ee]rror|[Ee]RROR|failed|FAILED ]]; then
                level="ERROR"
            elif [[ "$line" =~ ^[Ww]arn|[Ww]ARN ]]; then
                level="WARN"
            elif [[ "$line" =~ ^[Dd]ebug|[Dd]EBUG ]]; then
                level="DEBUG"
            fi
            
            # Escape JSON special characters in the line
            local escaped_line
            escaped_line=$(echo "$line" | sed 's/\\/\\\\/g; s/"/\\"/g')
            
            log_jsonl "$level" "$escaped_line" "{\"source\":\"opencode\"}"
        done < "$output_file"
    fi
    
    # Handle exit codes
    case $exit_code in
        0)
            log_jsonl "INFO" "Execution completed successfully" "{\"elapsedSecs\":$elapsed,\"exitCode\":0}"
            ;;
        124)
            log_jsonl "ERROR" "Execution timed out" "{\"elapsedSecs\":$elapsed,\"timeoutSecs\":$OPENCODE_EXECUTION_TIMEOUT_SECS}"
            cleanup_orphans
            exit 2
            ;;
        *)
            log_jsonl "ERROR" "Execution failed" "{\"elapsedSecs\":$elapsed,\"exitCode\":$exit_code}"
            cleanup_orphans
            exit 1
            ;;
    esac
    
    exit 0
}

# Run main
main "$@"
