#!/bin/bash
# Type checking with Astral's ty type checker
#
# Usage:
#   ./scripts/type-check.sh              # Run type checks on main code
#   ./scripts/type-check.sh --watch      # Watch mode (rerun on file changes)
#   ./scripts/type-check.sh --verbose    # Verbose output with detailed info
#   ./scripts/type-check.sh --help       # Show help

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
TYPE_CHECKER="ty"
CODE_PATH="python/confiture/"
WATCH_MODE=false
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --watch)
            WATCH_MODE=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "Type checking with Astral's ty type checker"
            echo ""
            echo "Usage: ./scripts/type-check.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --watch      Run in watch mode (rerun on file changes)"
            echo "  --verbose    Show verbose output with detailed info"
            echo "  --help       Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./scripts/type-check.sh                    # Run once"
            echo "  ./scripts/type-check.sh --watch           # Watch mode"
            echo "  ./scripts/type-check.sh --verbose         # Detailed output"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check if ty is installed
if ! command -v ty &> /dev/null; then
    echo -e "${RED}❌ ty type checker not found${NC}"
    echo "Install with: uv tool install ty"
    exit 1
fi

# Function to run type checking
run_type_check() {
    echo -e "${BLUE}🔍 Running type checks on ${CODE_PATH}${NC}"
    echo ""

    if [ "$VERBOSE" = true ]; then
        uv run ty check "$CODE_PATH" --verbose
    else
        uv run ty check "$CODE_PATH"
    fi

    local exit_code=$?

    echo ""
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✅ Type checking passed!${NC}"
    else
        echo -e "${RED}❌ Type checking failed with exit code $exit_code${NC}"
    fi

    return $exit_code
}

# Function to watch mode
watch_mode() {
    echo -e "${BLUE}👀 Watching for changes in ${CODE_PATH}${NC}"
    echo "Press Ctrl+C to stop"
    echo ""

    # Use inotify-tools if available, otherwise simple loop
    if command -v inotifywait &> /dev/null; then
        while true; do
            inotifywait -e modify,create,delete -r "$CODE_PATH" >/dev/null 2>&1
            clear
            run_type_check || true
        done
    else
        # Fallback: simple polling
        local last_check=0
        while true; do
            local current_time=$(date +%s)
            if [ $((current_time - last_check)) -ge 2 ]; then
                clear
                run_type_check || true
                last_check=$current_time
            fi
            sleep 1
        done
    fi
}

# Main execution
if [ "$WATCH_MODE" = true ]; then
    watch_mode
else
    run_type_check
fi
