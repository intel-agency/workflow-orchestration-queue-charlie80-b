#!/usr/bin/env bash
set -euo pipefail

# devcontainer-opencode.sh
#
# Shell-bridge dispatcher for the Sentinel orchestrator.
# Thin CLI wrapper around devcontainer for the opencode server workflow.
# Shared defaults mean callers only specify what differs.
#
# Commands:
#   up      Start (or reconnect to) the devcontainer
#   start   Ensure opencode serve is running inside the container
#   prompt  Dispatch a prompt to the agent via opencode run --attach
#   stop    Gracefully stop the container (keeps it for fast restart)
#   down    Stop and remove the container (full teardown)
#   status  Show container and server status
#
# Shared options (env or flag, all commands):
#   -c <config>   devcontainer.json path  (env: DEVCONTAINER_CONFIG,  default: .devcontainer/devcontainer.json)
#   -w <dir>      workspace folder        (env: WORKSPACE_FOLDER,     default: .)
#
# 'prompt' options:
#   -f <file>     assembled prompt file path (required, or use -p)
#   -p <prompt>   inline prompt string       (required, or use -f)
#   -u <url>      opencode server URL        (env: OPENCODE_SERVER_URL, default: http://127.0.0.1:4096)
#   -t <secs>     execution timeout          (env: OPENCODE_EXECUTION_TIMEOUT_SECS, default: 5700)
#   -l <dir>      log directory              (env: OPENCODE_LOG_DIR, default: ./logs)
#
# Exit Codes:
#   0 - Success
#   1 - General error
#   2 - Timeout exceeded (prompt command)
#   3 - Server connection failure (prompt command)
#   4 - Container not found (stop/down commands)

# Default configuration
DEVCONTAINER_CONFIG="${DEVCONTAINER_CONFIG:-.devcontainer/devcontainer.json}"
WORKSPACE_FOLDER="${WORKSPACE_FOLDER:-.}"
OPENCODE_SERVER_URL="${OPENCODE_SERVER_URL:-http://127.0.0.1:4096}"
OPENCODE_EXECUTION_TIMEOUT_SECS="${OPENCODE_EXECUTION_TIMEOUT_SECS:-5700}"
OPENCODE_LOG_DIR="${OPENCODE_LOG_DIR:-./logs}"
PROMPT_FILE=""
PROMPT_STRING=""

usage() {
    cat >&2 <<'EOF'
Usage: devcontainer-opencode.sh <command> [options]

Commands:
  up      Start (or reconnect to) the devcontainer
  start   Ensure opencode serve is running inside the container
  prompt  Dispatch a prompt file to the agent via opencode run --attach
  stop    Gracefully stop the container (keeps it; fast restart via 'up')
  down    Stop and remove the container (full teardown)
  status  Show container and server status

Shared options:
  -c <config>   Path to devcontainer.json (default: .devcontainer/devcontainer.json)
  -w <dir>      Workspace folder          (default: .)

'prompt' options:
  -f <file>     Assembled prompt file path (required, or use -p)
  -p <prompt>   Inline prompt string       (required, or use -f)
  -u <url>      opencode server URL        (default: http://127.0.0.1:4096)
  -t <secs>     execution timeout          (default: 5700)
  -l <dir>      log directory              (default: ./logs)

Environment variables:
  DEVCONTAINER_CONFIG, WORKSPACE_FOLDER, OPENCODE_SERVER_URL
  OPENCODE_EXECUTION_TIMEOUT_SECS, OPENCODE_LOG_DIR
  ZHIPU_API_KEY, KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY, GITHUB_TOKEN  (required for 'prompt')

Exit Codes:
  0   Success
  1   General error
  2   Timeout exceeded
  3   Server connection failure
  4   Container not found
EOF
    exit 1
}

# Log a message with timestamp
log() {
    local level="$1"
    shift
    local timestamp
    timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[$timestamp] [$level] [devcontainer-opencode] $*" >&2
}

# Get absolute path of workspace folder
get_abs_workspace() {
    cd "$WORKSPACE_FOLDER" && pwd
}

# Find container by devcontainer label
find_container() {
    local abs_workspace
    abs_workspace="$(get_abs_workspace)"
    docker ps -aq --filter "label=devcontainer.local_folder=${abs_workspace}"
}

# Get container state (running, exited, etc.)
get_container_state() {
    local container_id="$1"
    docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || echo "not_found"
}

# Check if container exists (any state)
container_exists() {
    local container_id
    container_id="$(find_container)"
    [[ -n "$container_id" ]]
}

# Check if container is running
container_running() {
    local container_id
    container_id="$(find_container)"
    if [[ -z "$container_id" ]]; then
        return 1
    fi
    local state
    state="$(get_container_state "$container_id")"
    [[ "$state" == "running" ]]
}

# Shared devcontainer arguments
shared_args() {
    echo "--workspace-folder" "$WORKSPACE_FOLDER" "--config" "$DEVCONTAINER_CONFIG"
}

# Command: up - Start or reconnect to devcontainer
cmd_up() {
    log "INFO" "Starting devcontainer"
    
    # Check if container already exists and is running
    if container_running; then
        local container_id
        container_id="$(find_container)"
        log "INFO" "Container already running: ${container_id}"
        return 0
    fi
    
    # Check if container exists but is stopped
    local container_id
    container_id="$(find_container)"
    if [[ -n "$container_id" ]]; then
        local state
        state="$(get_container_state "$container_id")"
        if [[ "$state" != "running" ]]; then
            log "INFO" "Restarting stopped container: ${container_id}"
            docker start "$container_id"
            # Wait for container to be ready
            sleep 2
        fi
    else
        # Create new container
        log "INFO" "Creating new devcontainer"
        devcontainer up $(shared_args)
    fi
    
    log "INFO" "Devcontainer ready"
}

# Command: start - Ensure opencode server is running inside container
cmd_start() {
    log "INFO" "Ensuring opencode server is running"
    
    # First ensure container is up
    if ! container_running; then
        log "INFO" "Container not running, starting via 'up'"
        cmd_up
    fi
    
    # Execute server start script inside container
    devcontainer exec $(shared_args) \
        -- bash ./scripts/start-opencode-server.sh
    
    log "INFO" "Opencode server started"
}

# Command: prompt - Execute prompt with timeout and JSONL logging
cmd_prompt() {
    if [[ -z "$PROMPT_FILE" && -z "$PROMPT_STRING" ]]; then
        log "ERROR" "-f <prompt-file> or -p <prompt> is required for the 'prompt' command"
        usage
    fi
    
    # Validate required environment variables
    local missing=()
    for var in ZHIPU_API_KEY KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY GITHUB_TOKEN; do
        if [[ -z "${!var:-}" ]]; then
            missing+=("$var")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        log "ERROR" "Missing required environment variables: ${missing[*]}"
        exit 1
    fi
    
    # Ensure container is running
    if ! container_running; then
        log "ERROR" "Devcontainer is not running. Use 'up' or 'start' first."
        exit 1
    fi
    
    # Build prompt argument
    local prompt_arg
    if [[ -n "$PROMPT_STRING" ]]; then
        prompt_arg=(-p "$PROMPT_STRING")
    else
        # Validate prompt file exists
        if [[ ! -f "$PROMPT_FILE" ]]; then
            log "ERROR" "Prompt file not found: $PROMPT_FILE"
            exit 1
        fi
        prompt_arg=(-f "$PROMPT_FILE")
    fi
    
    log "INFO" "Executing prompt with timeout: ${OPENCODE_EXECUTION_TIMEOUT_SECS}s"
    
    # Execute prompt inside container with environment injection
    devcontainer exec $(shared_args) \
        --remote-env ZHIPU_API_KEY="$ZHIPU_API_KEY" \
        --remote-env KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY="$KIMI_CODE_ORCHESTRATOR_AGENT_API_KEY" \
        --remote-env GITHUB_TOKEN="$GITHUB_TOKEN" \
        --remote-env GITHUB_PERSONAL_ACCESS_TOKEN="$GITHUB_TOKEN" \
        --remote-env GH_ORCHESTRATION_AGENT_TOKEN="${GH_ORCHESTRATION_AGENT_TOKEN:-}" \
        --remote-env OPENCODE_SERVER_URL="$OPENCODE_SERVER_URL" \
        --remote-env OPENCODE_EXECUTION_TIMEOUT_SECS="$OPENCODE_EXECUTION_TIMEOUT_SECS" \
        --remote-env OPENCODE_LOG_DIR="$OPENCODE_LOG_DIR" \
        --remote-env SENTINEL_ID="${SENTINEL_ID:-}" \
        --remote-env TASK_ID="${TASK_ID:-}" \
        -- bash ./scripts/run_opencode_prompt.sh \
            -a "$OPENCODE_SERVER_URL" \
            -t "$OPENCODE_EXECUTION_TIMEOUT_SECS" \
            -l "$OPENCODE_LOG_DIR" \
            "${prompt_arg[@]}"
    
    local exit_code=$?
    
    if [[ $exit_code -eq 0 ]]; then
        log "INFO" "Prompt execution completed successfully"
    else
        log "ERROR" "Prompt execution failed with exit code: $exit_code"
    fi
    
    exit $exit_code
}

# Command: stop - Gracefully stop the container
cmd_stop() {
    local container_id
    container_id="$(find_container)"
    
    if [[ -z "$container_id" ]]; then
        log "WARN" "No container found for workspace"
        exit 4
    fi
    
    local state
    state="$(get_container_state "$container_id")"
    
    if [[ "$state" != "running" ]]; then
        log "INFO" "Container already stopped: ${container_id}"
        return 0
    fi
    
    log "INFO" "Stopping container: ${container_id}"
    docker stop "$container_id"
    log "INFO" "Container stopped (preserved for fast restart)"
}

# Command: down - Stop and remove the container
cmd_down() {
    local container_id
    container_id="$(find_container)"
    
    if [[ -z "$container_id" ]]; then
        log "WARN" "No container found for workspace"
        exit 4
    fi
    
    local state
    state="$(get_container_state "$container_id")"
    
    # Stop if running
    if [[ "$state" == "running" ]]; then
        log "INFO" "Stopping container: ${container_id}"
        docker stop "$container_id"
    fi
    
    # Remove container
    log "INFO" "Removing container: ${container_id}"
    docker rm "$container_id"
    log "INFO" "Container removed (full teardown)"
}

# Command: status - Show container and server status
cmd_status() {
    local container_id
    container_id="$(find_container)"
    
    echo "=== DevContainer Status ==="
    echo ""
    
    if [[ -z "$container_id" ]]; then
        echo "Container: NOT FOUND"
        echo ""
        echo "Use 'up' to create and start the devcontainer."
        return 0
    fi
    
    local state
    state="$(get_container_state "$container_id")"
    
    echo "Container ID: ${container_id}"
    echo "Container State: ${state}"
    echo "Workspace: $(get_abs_workspace)"
    echo ""
    
    if [[ "$state" == "running" ]]; then
        echo "=== Server Status ==="
        echo ""
        
        # Check if opencode server is running inside container
        if devcontainer exec $(shared_args) -- curl -s -o /dev/null --connect-timeout 2 "$OPENCODE_SERVER_URL/" 2>/dev/null; then
            echo "Opencode Server: RUNNING at ${OPENCODE_SERVER_URL}"
        else
            echo "Opencode Server: NOT RESPONDING at ${OPENCODE_SERVER_URL}"
            echo ""
            echo "Use 'start' to start the opencode server."
        fi
    else
        echo "Server Status: N/A (container not running)"
        echo ""
        echo "Use 'up' to start the container."
    fi
}

# Parse command line arguments
if [[ $# -lt 1 ]]; then
    usage
fi

COMMAND="$1"
shift

while getopts ":c:w:f:p:u:t:l:" opt; do
    case $opt in
        c) DEVCONTAINER_CONFIG="$OPTARG" ;;
        w) WORKSPACE_FOLDER="$OPTARG" ;;
        f) PROMPT_FILE="$OPTARG" ;;
        p) PROMPT_STRING="$OPTARG" ;;
        u) OPENCODE_SERVER_URL="$OPTARG" ;;
        t) OPENCODE_EXECUTION_TIMEOUT_SECS="$OPTARG" ;;
        l) OPENCODE_LOG_DIR="$OPTARG" ;;
        *) usage ;;
    esac
done

# Execute command
case "$COMMAND" in
    up)
        cmd_up
        ;;
    start)
        cmd_start
        ;;
    prompt)
        cmd_prompt
        ;;
    stop)
        cmd_stop
        ;;
    down)
        cmd_down
        ;;
    status)
        cmd_status
        ;;
    *)
        log "ERROR" "Unknown command: ${COMMAND}"
        usage
        ;;
esac
