#!/usr/bin/env bash
# Run python unit tests on test datasets without deleting user datasets.
# This script differs to `runtests.sh` in that existing containers are stopped
# before a test contain is made and restarted once tests have ran.

# Exit when any command fails
set -e

function command_help {
   echo "Run the test suite."
   echo
   echo "Usage:"
   echo "  testcode.sh [options]"
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

POSTGRES_CONTAINER=docker.io/postgres:14
CONTAINER_NAME=unittests
POSTGRES_PORT=5432 # same as active database
read -ra DOCKER_CONTAINERS < <(docker container ls -q)

function setup {
    set +x
    if [ "$SKIP_DATABASE" = true ]; then
        set -x
        return 0
    fi

    echo -e "\nStopping active containers"
    docker stop "${DOCKER_CONTAINERS[@]}"

    echo -e "\nStarting up unitesting postgres container"
    set -x
    $CONTAINER_ENGINE pull $POSTGRES_CONTAINER
    $CONTAINER_ENGINE run --detach \
        --name $CONTAINER_NAME \
        --env POSTGRES_PASSWORD=password \
        --publish $POSTGRES_PORT:5432 \
        $POSTGRES_CONTAINER
    sleep 3
}

function cleanup {
    set +x
    if [ "$SKIP_DATABASE" = true ]; then
        set -x
        return 0
    fi

    echo -e "\nCleaning up unitesting postgres container"
    set -x
    $CONTAINER_ENGINE stop $CONTAINER_NAME
    $CONTAINER_ENGINE container rm $CONTAINER_NAME

    set +x
    echo -e "\nRestarting previously active containers"
    set -x
    docker start "${DOCKER_CONTAINERS[@]}"
}

# Call cleanup before exit
trap cleanup EXIT

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
