#!/usr/bin/env bash
# shellcheck disable=SC1004

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
   echo "  -c=config      Run a CI test configuration (main, routes, migrations)."
   echo "  -e='flags'     Pass extra flags to pytest (must be quoted)."
   echo "  -d             Don't deploy a database using a container engine."
   echo "  -s             Start a local postgres container with SSL enabled."
   echo
}

CONTAINER_ENGINE=docker
SSL_DATABASE=false
CLEANUP_DONE=false
while getopts "hpc:e:ds" option; do
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
        s) # Enable SSL for local postgres container
            SSL_DATABASE=true;;
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

    if [ "$SSL_DATABASE" = true ]; then
        echo -e "\nStarting up SSL-enabled postgres container"
        CERT_DIR=$(mktemp -d)
        openssl req -new -x509 -days 7 -nodes \
            -subj "/CN=localhost" \
            -keyout "$CERT_DIR/server.key" \
            -out "$CERT_DIR/server.crt"
        chmod 600 "$CERT_DIR/server.key"
        chmod 644 "$CERT_DIR/server.crt"

        set -x
        $CONTAINER_ENGINE run -d --name rctab_test_postgres_ssl \
            -e POSTGRES_PASSWORD=password \
            -e POSTGRES_USER=postgres \
            -e POSTGRES_DB=postgres \
            -p 5432:5432 \
            -v "$CERT_DIR:/tmp/certs" \
            --entrypoint bash \
            postgres:17 \
            -c 'set -euo pipefail
            install -m 600 /tmp/certs/server.key /var/lib/postgresql/server.key
            install -m 644 /tmp/certs/server.crt /var/lib/postgresql/server.crt
            chown postgres:postgres /var/lib/postgresql/server.key /var/lib/postgresql/server.crt
            exec docker-entrypoint.sh postgres \
              -c ssl=on \
              -c ssl_cert_file=/var/lib/postgresql/server.crt \
              -c ssl_key_file=/var/lib/postgresql/server.key'
        set +x

        for _ in {1..60}; do
            if $CONTAINER_ENGINE exec rctab_test_postgres_ssl pg_isready -U postgres > /dev/null 2>&1; then
                set -x
                return 0
            fi
            sleep 1
        done

        echo "Postgres did not become ready in time"
        $CONTAINER_ENGINE logs rctab_test_postgres_ssl || true
        exit 1
    fi

    echo -e "\nStarting up postgres container"
    set -x
    $CONTAINER_ENGINE compose -f compose/docker-compose.yaml --profile db_only up --detach
    sleep 3
}

function cleanup {
    if [ "$CLEANUP_DONE" = true ]; then
        return 0
    fi
    CLEANUP_DONE=true

    set +x
    if [ "$SKIP_DATABASE" = true ]; then
        set -x
        return 0
    fi

    if [ "$SSL_DATABASE" = true ]; then
        echo -e "\nCleaning up SSL-enabled postgres container"
        set -x
        $CONTAINER_ENGINE rm -f rctab_test_postgres_ssl || true
        if [ -n "$CERT_DIR" ]; then
            rm -rf "$CERT_DIR"
        fi
        return 0
    fi

    echo -e "\nCleaning up postgres container"
    set -x
    $CONTAINER_ENGINE compose -f compose/docker-compose.yaml --profile db_only down
}

function cleanup_on_exit {
    EXIT_CODE=$?
    cleanup || true
    exit "$EXIT_CODE"
}

trap cleanup_on_exit EXIT
trap 'exit 130' SIGINT
trap 'exit 143' SIGTERM

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

# When running against our SSL-enabled local test DB, force SSL in app settings.
if [ "$SSL_DATABASE" = true ]; then
    export SSL_REQUIRED=true
fi

# You can override settings from either of the example .env files here e.g.
# SESSION_EXPIRE_TIME_MINUTES=1

# Stop automatically exporting variables
set +a

# Create schema but don't start Celery, Redis, etc.
sleep 5
poetry run alembic upgrade head

# Run tests
export TESTING=true
if [ "$TEST_CONFIGURATION" = "main" ]; then
    # Collect coverage from a clean baseline but don't print a report yet: on its
    # own the "main" configuration excludes tests/test_routes/ and so reports
    # misleadingly low coverage. The combined report is printed by the "routes"
    # configuration, which appends to the .coverage data this run produces.
    CONFIGURATION_ARGS=(--hypothesis-show-statistics --cov-report= --cov rctab --ignore tests/test_routes/)
    poetry run pytest "${EXTRA_ARGS[@]}" "${CONFIGURATION_ARGS[@]}"
elif [ "$TEST_CONFIGURATION" = "routes" ]; then
    # Append route-test coverage to any data left by the "main" configuration and
    # print the combined report, so coverage reflects the whole test suite.
    CONFIGURATION_ARGS=(--cov-append --cov-report term-missing --cov rctab ./tests/test_routes/)
    poetry run pytest "${EXTRA_ARGS[@]}" "${CONFIGURATION_ARGS[@]}"
elif [ "$TEST_CONFIGURATION" = "migrations" ]; then
    poetry run alembic upgrade head
    poetry run alembic downgrade b65796c99771
    poetry run alembic upgrade head
else
    poetry run pytest "${EXTRA_ARGS[@]}"
fi
