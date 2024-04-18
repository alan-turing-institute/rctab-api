# Setup

## Local Setup

To run the API locally (e.g. for development):

1. Clone the repo.
1. [Set up Poetry](#set-up-poetry)
1. [Set up Pre-Commit](#set-up-pre-commit)
1. You will need to set some environment variables.
   Instructions are in the [Server Configuration](#server-configuration) section.
1. You have the option of either installing the RCTab API natively or building a Docker container.
   **Note** that unit tests are currently only supported with the "Run Natively" method.
   - For the former, see [Run Natively](#run-natively)
   - For the latter, see [Run in a Container](#run-in-a-container).

### Set up Poetry

Make sure you have [Poetry](https://python-poetry.org/docs/) installed.

Start by setting up the environment:

```bash
poetry env use python3
```

Now spawn a poetry shell, this will create a virtual environment for the project.
**Keep this virtual environment activated for the remaining steps.**

```bash
poetry shell
```

Install Python dependencies specified in the ``poetry.lock`` file:

```bash
poetry install
```

All required packages should now be installed.

### Set up Pre-Commit

Linting is managed by [Pre-Commit](https://pre-commit.com).
Install the Pre-Commit hooks:

```bash
pre-commit install
```

set an environment variable with your [safety API key](https://docs.safetycli.com/safety-docs/support/invalid-api-key-error#how-to-get-a-safety-api-key):

```bash
export SAFETY_API_KEY=your-api-key
```

and run the checks with:

```bash
pre-commit run --all-files
```

They should all pass.

### Server Configuration

The web app is configured through a series of environment variables, read by a Pydantic [BaseSettings](https://pydantic-docs.helpmanual.io/usage/settings/) class.
Create a minimal `.env` file for the web app by copying the example environment file:

```bash
cp example.env .env
```

If you end up using a PostgreSQL port other than `5432` or a password other than `password` in the [PostgreSQL Container](#postgresql-container) section then you should edit `.env` to specify `DB_PORT` and/or `DB_PASSWORD`.
For the full range of settings, see the ``settings.py`` module.

Create a minimal `.auth.env` file for [Microsoft Authentication Library (MSAL)](https://learn.microsoft.com/en-us/azure/active-directory/develop/msal-overview) by copying the example:

```bash
cp example.auth.env .auth.env
```

Note that these are only suitable for getting a development environment up and running.
Never add  `.env` nor `.auth.env` to version control and do not use the default password or session secret in a real deployment.
For the full explanation of the auth settings, see [Application Registration](#application-registration).

[//]: # (If you wish to send email notifications, set up a SendGrid account and then replace `{YOUR_SENDGRID_KEY} with a SendGrid API key.)

### Run Natively

#### Pre-requisites

Make sure you are inside the virtual environment and have [Set up Poetry](#set-up-poetry).

If you are using macOS, you may need to install some libraries that are needed for PDF generation.
You might want to do this with Homebrew:

```bash
brew install cairo pango libffi
```

If you continue to get "library not found" errors when running the RCTab API or unit tests then you may need to find the `brew` library directory and prepend it to your DYLD_LIBRARY_PATH environment variable with something like:

```bash
export DYLD_LIBRARY_PATH="/opt/homebrew/lib/:$DYLD_LIBRARY_PATH"
```

#### PostgreSQL Container

The RCTab API web server needs a PostgreSQL database to store Azure subscription and user details.
You can install PostgreSQL on your development machine (e.g. with Homebrew) or use a container.
If you want to use the latter option, you can install Docker and run:

```bash
docker create \
       --name rctab_db \
       --publish 5432:5432 \
       --env POSTGRES_PASSWORD=password \
       --volume "$(pwd)/.postgresdata":"/var/lib/postgresql/data" \
       postgres:14
```

This will create a container based on the latest PostgreSQL 14 image on DockerHub and

- name it `rctab_db`
- expose port 5432 on the container as port 5432 on the host
- set the default `postgres` user's password to `password`

It also creates a directory called `.postgresdata` in the current directory and mount it on the container as the default PostgreSQL data directory.
This is optional but makes it easy to delete the test data with `rm -r .postgresdata`.

You can now start the container with

```bash
docker start rctab_db
```

You can stop it at any time with `docker stop rctab_db`.

#### Create Database Schema

Before you start the API we must create the database schema:

```bash
scripts/prestart.sh
```

#### Running Tests

##### Manually

With the Poetry shell activated and our PostgreSQL database running, we can run tests with

```bash
TESTING=true pytest tests/
```

The `TESTING=true` env var is important so that database commits are rolled back between each unit test.

**Note:** This will remove the contents of any [postgreSQL containers](#postgresql-container) you have running. If you don't want to lose them use [the helper script](#with-the-helper-script).

The tests for background tasks require Redis
Once you have a [Redis server](https://redis.io/docs/install/install-redis/) running (or a [Redis Docker](https://hub.docker.com/_/redis) container running), you can run the unit tests, including the background task tests, with:

```bash
TESTING=true CELERY_RESULT_BACKEND="redis://localhost:6379/0" pytest tests/
```

##### With the Helper Script

With the Poetry shell activated but no PostgreSQL database running (to avoid port conflicts), we can run all tests with:

```bash
./scripts/runtests.sh
```

`runtests.sh` is a convenience script that creates a temporary database, using Docker or Podman, for the duration of the test suite.

By default, the script will pull and run a Postgres container, set appropriate environment variables and run all tests.
The container will be cleaned up after the tests conclude (or fail).
The container image will not be removed.
To use Podman instead of Docker, use the `-p` flag.
Extra arguments can be passed to pytest using the `-e flag`.
_e.g._ `./scripts/runtests.sh -e '-vvv'`.
To see all options run `./scripts/runtests.sh -h`.

Note: Running this tests this way, or manually, will remove any existing data in the local database. To run the tests without removing existing data use:

```bash
./scripts/testcode.sh
```

This does the same thing as `runtests.sh` but any existing/running databases are stopped first to ensure the testing doesn't wipe them. They are then restarted once the script has finished. This means your databases will not be removed by running tests.

#### Run the API in Development Mode

To start the API server run:

```bash
uvicorn rctab:app --reload --reload-dir rctab
```

You should be able to view the Login page, but you will not be able to log in until you have completed the [Application Registration](#application-registration) steps.

### Run in a Container

#### Build

A container image of the web app can be built using the [Dockerfile](https://github.com/alan-turing-institute/rctab-api/tree/main/Dockerfile).

For example,

```bash
docker build -t rctab:latest .
```

or, using Podman,

```bash
podman build -t rctab:latest .
```

#### Run

It is easiest to start a database and RCTab API server with the [`docker-compose-local.yaml`](https://github.com/alan-turing-institute/rctab-api/tree/main/compose/docker-compose-local.yaml) file:

```bash
docker-compose -f compose/docker-compose-local.yaml up -d
```

and stop it with:

```bash
docker-compose -f compose/docker-compose-local.yaml down
```

Podman also supports Docker Compose since Podman 3.0.0.
This will require starting the `podman.service` systemd unit and pointing Docker Compose to `podman.socket` using the `DOCKER_HOST` environment variable.

For example,

```bash
systemctl --user start podman.service
export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"
```

If you do not want Docker Compose to start a database for you (e.g. because you have manually started a separate [PostgreSQL Container](#postgresql-container) or because you are connecting to an external database), you can use the other Compose file:

```bash
docker-compose -f compose/docker-compose-external.yaml up -d
```

**Note** that environment variables declared in the compose file will override those from env files.

#### Visit the Homepage

You should be able to view the login page at `http://localhost:8000`, but you will not be able to log in until you have completed the [Application Registration](#application-registration) steps.

## Application Registration

RCTab uses the Microsoft Authentication Library (MSAL) for authentication.
[This](https://docs.microsoft.com/en-us/azure/active-directory/develop/web-app-quickstart?pivots=devlang-python#how-the-sample-works) diagram gives some idea of the authentication flow.
For it to work, you will need to change the dummy `TENANT_ID`, `CLIENT_ID` and `CLIENT_SECRET` values in `.auth.env` that were created in the [Server Configuration](#server-configuration) step.

If you are joining an existing RCTab project, someone will have already registered an application with Azure Active Directory (AD).
In that case, whoever registered the application will need to share the Azure AD Tenant ID, the Application ID (a.k.a. Client ID) and Client Secret with you.

If an application hasn't already been registered, Microsoft's instructions are [here](https://docs.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app#configure-platform-settings).
Your organisation should already have an AD Tenant ID, the Application ID will be given to you during the registration process, and you will need to generate a Client Secret.

## Accounting Routes

Accounting routes (those in [rctab/routers/accounting](https://github.com/alan-turing-institute/rctab-api/tree/main/rctab/routers/accounting)) use JSON Web Tokens ([JWT](https://jwt.io/introduction)) to authenticate.
Some routes are only used by the RCTab function apps.
The apps sign a JWT with a private key, and the API must have the corresponding public key to verify the token.
There are instructions for generating the key pairs in the Function Apps' docs.
Once generated, you can come back here and append the public keys to your `.env` file.

You will want to do something like:

```bash
echo USAGE_FUNC_PUBLIC_KEY={public-key-contents} >> .env
```

where `public-key-contents` is a string containing the contents of the Usage function's public key.

## Infrastructure Deployment

New versions of the RCTab API are deployed via a GitHub workflow which builds an image and pushes it to DockerHub.
The Docker image is pushed by GitHub whenever a new release is made and pulled by Azure whenever the RCTab API web app restarts.

To change the deployed infrastructure or to deploy a new Pulumi [stack](https://www.pulumi.com/docs/intro/concepts/stack/), see the RCTab Infrastructure docs.

If you need to manually build a Docker image and push it to DockerHub, the steps are (approximately):

1. `docker build -t my-dockerhub-id/rctab:my-image-tag .`
1. `docker push my-dockerhub-id/rctab:my-image-tag`
