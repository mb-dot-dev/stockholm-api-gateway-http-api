# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Dependency management and tooling are driven by [uv](https://docs.astral.sh/uv/) and exposed via the `Makefile`:

- `make install-dev` — install all dependencies (frozen lockfile)
- `make unit` — run the test suite (`uv run --frozen pytest`; `testpaths` in `pyproject.toml` scopes collection to `tests/`)
- Run a single test: `uv run --frozen pytest tests/test_producer.py::test_name`
- `make lint` — `ruff check`, `ruff format --check`, and `ty check` (the `ty` type checker)
- `make format` — apply `ruff format`
- `make test` — `lint` + `unit` (the full local gate)
- `make cfn-lint` — lint all CloudFormation/SAM templates (`aws/*.yml` and `*-template.yaml`)

Tests live in `tests/` (a package — `tests/__init__.py` makes pytest put the repo root on `sys.path`, so `from app import ...` resolves without installing the project). Boto3 clients are accessed via cached factories in `app/clients.py` (e.g. `get_sqs_client`) so importing a handler module has no AWS side effects — in handler tests, use moto (`mock_aws`) with a real queue rather than patching `get_sqs_client`; an `autouse` fixture calls `cache_clear()` before each test so a fresh client is created inside the mock context.

## Lambda packaging

The Lambda deployment artifact is a single `lambda.zip` shared by **both** Lambda functions (the handler path selects which one runs):

- `make build-lambda-package` — exports `requirements.txt`, pip-installs deps targeting `x86_64-manylinux2014` / Python 3.14 into `build/`, copies `app/` in, and zips it.

When changing dependencies, the zip must be rebuilt for the change to reach Lambda. CI runs this on every push.

## Architecture

This is an asynchronous, fully serverless ingest pipeline on AWS. Request flow:

```
Client → API Gateway (HTTP API v2, Auth0 JWT authorizer) → Producer Lambda → SQS → Consumer Lambda
```

- **Producer Lambda** (`app.api_gateway.lambda_handler`) — the single entry point wired to API Gateway via `AWS_PROXY` integration. It owns the module-level `APIGatewayHttpResolver` and registers the routers from `app/producer.py` (`POST /`) and `app/oauth.py` (`POST /oauth/token`). API Gateway validates the Auth0 JWT *before* invoking the `POST /` route. `app/producer.py` then applies a second-layer **IP allowlist** check (`ALLOWED_IPS` env var, CIDR-aware) and, if allowed, enqueues the raw request body to SQS. Returns `202` on success, `403` if the source IP is not allowed, `500` on SQS failure.
- **Consumer** (`app/consumer.py`) — SQS-triggered (`BatchSize: 1`), uses Powertools `BatchProcessor` with `ReportBatchItemFailures` for partial-batch failure handling. Currently just logs each record's JSON body — this is where downstream processing goes.
- Both handlers use **aws-lambda-powertools** (`Logger` and `Metrics`, namespace `"Stockholm"` hardcoded in each module rather than via env var — `Metrics()` resolves its namespace at construction time, before per-test env patching would take effect). `POWERTOOLS_SERVICE_NAME` / `POWERTOOLS_LOG_LEVEL` are set per-function in the SAM templates. Custom EMF metrics cover failure/denial paths that don't surface in Lambda's default `Errors` metric because the handlers catch and return a normal response rather than raising: `RequestDenied` (dimensioned by `reason`: `IpAllowlist` / `ClientIdAllowlist`) and `EnqueueFailure` in the producer route (`app/producer.py`), `BatchItemFailure` in the consumer's `record_handler` (`app/consumer.py`).

### Infrastructure model

Infrastructure is split across many small CloudFormation/SAM stacks, deployed **in dependency order entirely by GitHub Actions** (`.github/workflows/main.yaml`) — there is no single root template. Each stack exports outputs that later stacks consume as parameters. The deploy order and data flow are documented in the Mermaid diagram in `README.md`. Key stacks:

- `aws/application.yml` — AppRegistry application; exports the app tag key/value applied to all other resources.
- `aws/sqs.yml` — the queue (`VisibilityTimeout`/retention both 300s).
- `aws/producer-iam-role.yml`, `aws/consumer-iam-role.yml` — Lambda execution roles. Roles are created **separately and before** the Lambdas (the SAM templates reference them by ARN via `LambdaExecutionRoleArn`).
- `producer-template.yaml`, `consumer-template.yaml` — the two SAM Lambda stacks (root-level, not under `aws/`). Deployed with `sam deploy` directly in CI, not via the reusable workflow.
- `aws/api-gateway.yml` — HTTP API v2, JWT authorizer (`JwtIssuer`/`JwtAudience` from repo vars), route, integration, invoke permission, access logging.
- `aws/sqs-policy.yml` — the queue policy granting the producer role `SendMessage` and the consumer role receive/delete; deployed last because it needs both role ARNs and the queue.

Most `aws/*.yml` stacks deploy through the shared reusable workflow `mb-dot-dev/reusable-workflows/.github/workflows/deploy-cloudformation.yaml`, which returns each stack's outputs as `stack-outputs-json` for downstream `fromJSON(...)` wiring.

### Deployment & CI notes

- `PROJECT_NAME` is `stockholm` (set in the workflow `env`); resources are named `stockholm-*`. The `name` field in `pyproject.toml` (`stockholm-api-gateway-http-api`) is unrelated to the deployed stack names.
- Deploys (the `prepare` job and everything gated on it) run **only on push to `main`** — pull requests run lint/build/cfn-lint but do **not** deploy.
- AWS auth is via OIDC (`DEPLOY_ROLE_ARN` secret); region is `eu-central-1`. `ALLOWED_IPS` and the `JWT_ISSUER`/`JWT_AUDIENCE` repo vars are injected at deploy time, not committed.

## Conventions

- Python 3.14, `ruff` with a broad rule set and 120-char lines (see `[tool.ruff.lint]` in `pyproject.toml`). Type-checked with `ty`.
- `from __future__ import annotations` + `TYPE_CHECKING` imports for Powertools/typing-only symbols is the established pattern in both handlers.
- `tests/**` and `scripts/**` have relaxed lint rules (asserts, magic values, prints) configured in `per-file-ignores`.
