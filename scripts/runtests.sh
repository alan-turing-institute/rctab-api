#!/usr/bin/env bash

# Exit when any command fails
set -e

function command_help {
   echo "Run the test suite."
   echo
   echo "Usage:"
   echo "  runtests.sh [options]"
   echo
   echo "options:"
   echo "  -h             Print this message and exit."
   echo "  -p             Use Podman instead of Docker as the container engine."
   echo "  -c=config      Run a CI test configuration (main, routes)."
   echo "  -e='flags'     Pass extra flags to pytest (must be quoted)."
   echo "  -d             Don't deploy a database using a container engine."
   echo
}

CONTAINER_ENGINE=docker
while getopts "hpc:e:d" option; do
    case $option in
        h) # Help
            command_help
            exit;;
        p) # Podman
            CONTAINER_ENGINE=podman;;
        c) # Test configuration
            TEST_CONFIGURATION=$OPTARG;;
        e) # Extra pytest arguments
            IFS=' ' read -ra EXTRA_ARGS <<< "$OPTARG";;
        d) # Don't deploy a database
            SKIP_DATABASE=true;;
        \?)
            exit 2;;
    esac
done
shift $((OPTIND-1))

function setup {
    set +x
    if [ "$SKIP_DATABASE" = true ]; then
        set -x
        return 0
    fi

    echo -e "\nStarting up postgres container"
    set -x
    $CONTAINER_ENGINE compose -f compose/docker-compose-local-unittests.yaml up -d
    sleep 3
}

function cleanup {
    set +x
    if [ "$SKIP_DATABASE" = true ]; then
        set -x
        return 0
    fi

    echo -e "\nCleaning up postgres container"
    set -x
    docker compose -f compose/docker-compose-local-unittests.yaml down
}

# Call cleanup if this script is cancelled with Ctrl-C
trap cleanup SIGINT

# Print commands being executed
set -x

setup

# Automatically export any variables we define or source
set -a

# Set environment variables for MSAL auth (not used but must be present)
# shellcheck disable=SC1091
source example.auth.env

# Set webapp environment variables
# shellcheck disable=SC1091
source example.env

# You can override settings from either of the example .env files here e.g.
# SESSION_EXPIRE_TIME_MINUTES=1

# Stop automatically exporting variables
set +a

# Create schema but don't start Celery, Redis, etc.
sleep 5
poetry run alembic upgrade head

# Run tests
if [ "$TEST_CONFIGURATION" = "main" ]; then
    CONFIGURATION_ARGS=(--hypothesis-show-statistics --cov-report term-missing --cov rctab --ignore tests/test_routes/)
elif [ "$TEST_CONFIGURATION" = "routes" ]; then
    CONFIGURATION_ARGS=(./tests/test_routes/)
fi
export TESTING=true
poetry run pytest "${EXTRA_ARGS[@]}" "${CONFIGURATION_ARGS[@]}"

cleanup
