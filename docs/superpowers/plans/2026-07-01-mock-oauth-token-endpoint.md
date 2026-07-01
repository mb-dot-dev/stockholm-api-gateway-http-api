# Mock OAuth Token Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /oauth/token` to the existing API Gateway HTTP API, served by the producer Lambda refactored to use `APIGatewayHttpResolver`, logging headers + body and returning a signed Okta-style JWT.

**Architecture:** The producer Lambda gains a module-level `APIGatewayHttpResolver`; `lambda_handler` delegates to it unconditionally. Token-issuance logic lives in a new `app/oauth.py` module registered via a Powertools `Router`. API Gateway gets a second route (`POST /oauth/token`, `AuthorizationType: NONE`) wired to the existing Lambda integration — no new Lambda, IAM role, or integration resource.

**Tech Stack:** Python 3.14, aws-lambda-powertools (`APIGatewayHttpResolver`, `Router`, `Response`, `Logger`), PyJWT (HS256 signing), moto/pytest (tests), ruff + ty (lint/types), cfn-lint (CloudFormation).

## Global Constraints

- Python `>=3.14`; `from __future__ import annotations` at the top of every `app/` file
- `TYPE_CHECKING` guard for typing-only imports (existing pattern)
- 120-char line limit; double quotes; ruff rule set as configured in `pyproject.toml`
- All functions must carry full type annotations (`ANN` rules are enforced)
- Run `make test` (lint + unit) before every commit to confirm the gate is green
- Run `make cfn-lint` after any change to `aws/*.yml`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add `PyJWT>=2.0` to `[project.dependencies]` |
| `uv.lock` | Generated | Updated by `uv add` |
| `app/oauth.py` | **Create** | `Router` + `issue_token()` handler + `_parse_client_id()` helper |
| `app/producer.py` | Modify | Replace `@event_source` with `APIGatewayHttpResolver`; include oauth router |
| `tests/test_oauth.py` | **Create** | Tests for the token endpoint |
| `tests/test_producer.py` | Modify | Update one exact-dict assertion to field checks (resolver adds fields) |
| `aws/api-gateway.yml` | Modify | Add `OAuthTokenRoute` resource |

---

## Task 1: Add PyJWT dependency

**Files:**
- Modify: `pyproject.toml`
- Generated: `uv.lock`

**Interfaces:**
- Produces: `import jwt` available in `app/oauth.py` and `tests/test_oauth.py`

- [ ] **Step 1: Add the dependency**

```bash
uv add "PyJWT>=2.0"
```

Expected: `pyproject.toml` gains `"PyJWT>=2.0"` under `[project.dependencies]`; `uv.lock` is updated. No output required beyond the uv success message.

- [ ] **Step 2: Verify it imports**

```bash
uv run --frozen python -c "import jwt; print(jwt.__version__)"
```

Expected: prints a version string like `2.x.x`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add PyJWT dependency for mock token signing"
```

---

## Task 2: Create `app/oauth.py` with tests

**Files:**
- Create: `app/oauth.py`
- Create: `tests/test_oauth.py`

**Interfaces:**
- Consumes: `jwt` (PyJWT from Task 1)
- Produces:
  - `app.oauth.router` — a `Router` instance with `POST /oauth/token` registered; imported by `app/producer.py` in Task 3
  - `app.oauth._MOCK_SIGNING_SECRET` — module-level `str`; imported by tests to decode tokens

- [ ] **Step 1: Write `tests/test_oauth.py`**

Create `tests/test_oauth.py` with the full content below. These tests will fail until `app/oauth.py` exists and is wired into the resolver (Task 3). Run them after Task 3 step 3 to confirm they pass.

```python
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import jwt
import pytest

from app import producer
from app.oauth import _MOCK_SIGNING_SECRET

if TYPE_CHECKING:
    from tests.conftest import FakeLambdaContext


def _build_token_event(
    body: str = "client_id=test-client&grant_type=client_credentials",
    content_type: str = "application/x-www-form-urlencoded",
) -> dict:
    return {
        "version": "2.0",
        "routeKey": "POST /oauth/token",
        "rawPath": "/oauth/token",
        "rawQueryString": "",
        "headers": {"content-type": content_type},
        "body": body,
        "requestContext": {
            "http": {
                "method": "POST",
                "path": "/oauth/token",
                "sourceIp": "1.2.3.4",
            },
        },
    }


def test_token_endpoint_returns_200(lambda_context: FakeLambdaContext) -> None:
    response = producer.lambda_handler(_build_token_event(), lambda_context)
    assert response["statusCode"] == 200


def test_token_response_shape(lambda_context: FakeLambdaContext) -> None:
    response = producer.lambda_handler(_build_token_event(), lambda_context)
    body = json.loads(response["body"])
    assert "access_token" in body
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["scope"] == "openid"


def test_token_has_okta_style_claims(lambda_context: FakeLambdaContext) -> None:
    response = producer.lambda_handler(_build_token_event(), lambda_context)
    token = json.loads(response["body"])["access_token"]
    claims = jwt.decode(token, _MOCK_SIGNING_SECRET, algorithms=["HS256"], audience="api://default")
    assert claims["sub"] == "test-client"
    assert claims["cid"] == "test-client"
    assert claims["aud"] == "api://default"
    assert "iss" in claims
    assert "exp" in claims
    assert "iat" in claims


def test_client_id_from_form_body_reflected_in_claims(lambda_context: FakeLambdaContext) -> None:
    event = _build_token_event(body="client_id=my-app&grant_type=client_credentials")
    response = producer.lambda_handler(event, lambda_context)
    token = json.loads(response["body"])["access_token"]
    claims = jwt.decode(token, _MOCK_SIGNING_SECRET, algorithms=["HS256"], audience="api://default")
    assert claims["sub"] == "my-app"
    assert claims["cid"] == "my-app"


def test_missing_client_id_falls_back_to_mock_client(lambda_context: FakeLambdaContext) -> None:
    event = _build_token_event(body="grant_type=client_credentials")
    response = producer.lambda_handler(event, lambda_context)
    token = json.loads(response["body"])["access_token"]
    claims = jwt.decode(token, _MOCK_SIGNING_SECRET, algorithms=["HS256"], audience="api://default")
    assert claims["sub"] == "mock-client"
    assert claims["cid"] == "mock-client"


def test_client_id_from_json_body_reflected_in_claims(lambda_context: FakeLambdaContext) -> None:
    event = _build_token_event(
        body=json.dumps({"client_id": "json-client"}),
        content_type="application/json",
    )
    response = producer.lambda_handler(event, lambda_context)
    token = json.loads(response["body"])["access_token"]
    claims = jwt.decode(token, _MOCK_SIGNING_SECRET, algorithms=["HS256"], audience="api://default")
    assert claims["sub"] == "json-client"
    assert claims["cid"] == "json-client"
```

- [ ] **Step 2: Create `app/oauth.py`**

```python
from __future__ import annotations

import json
import os
import time
import urllib.parse

import jwt
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import Router
from aws_lambda_powertools.event_handler.api_gateway import Response

logger = Logger()
router = Router()

_MOCK_SIGNING_SECRET = "mock-only-not-a-real-secret-do-not-use-in-production"  # noqa: S105
_DEFAULT_ISSUER = "https://mock-okta.example.com/oauth2/default"


@router.post("/oauth/token")
def issue_token() -> Response:
    event = router.current_event
    headers = dict(event.headers or {})
    body = event.body or ""

    logger.info("OAuth token request", extra={"headers": headers, "body": body})

    content_type = headers.get("content-type", "")
    client_id = _parse_client_id(body, content_type)

    now = int(time.time())
    claims = {
        "iss": os.environ.get("MOCK_ISSUER", _DEFAULT_ISSUER),
        "sub": client_id,
        "cid": client_id,
        "aud": "api://default",
        "iat": now,
        "exp": now + 3600,
        "scp": ["openid"],
    }
    token = jwt.encode(claims, _MOCK_SIGNING_SECRET, algorithm="HS256")

    return Response(
        status_code=200,
        content_type="application/json",
        body=json.dumps({
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid",
        }),
    )


def _parse_client_id(body: str, content_type: str) -> str:
    if not body:
        return "mock-client"
    if "application/json" in content_type:
        try:
            data = json.loads(body)
            return data.get("client_id", "mock-client") if isinstance(data, dict) else "mock-client"
        except json.JSONDecodeError:
            return "mock-client"
    params = urllib.parse.parse_qs(body)
    values = params.get("client_id", ["mock-client"])
    return values[0]
```

- [ ] **Step 3: Run lint on the new file**

```bash
uv run --frozen ruff check app/oauth.py && uv run --frozen ruff format --check app/oauth.py
```

Expected: no output (clean). Fix any reported issues before proceeding.

- [ ] **Step 4: Commit**

```bash
git add app/oauth.py tests/test_oauth.py
git commit -m "feat: add app/oauth.py with mock token handler and tests"
```

Note: tests are not runnable yet — `producer.py` still uses the old handler. They will pass after Task 3.

---

## Task 3: Refactor `app/producer.py` and verify tests

**Files:**
- Modify: `app/producer.py`
- Modify: `tests/test_producer.py` (one assertion)

**Interfaces:**
- Consumes: `app.oauth.router` from Task 2
- Produces: `producer.lambda_handler(event: dict[str, object], context: LambdaContext) -> dict[str, object]` — resolves both `POST /` and `POST /oauth/token`

- [ ] **Step 1: Replace `app/producer.py` with the refactored version**

Replace the entire file content with:

```python
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.api_gateway import Response
from botocore.exceptions import ClientError

from app.allowlist import is_allowed, parse_allowed_networks
from app.clients import get_sqs_client
from app.oauth import router as oauth_router

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
app = APIGatewayHttpResolver()
app.include_router(oauth_router)


@app.post("/")
def _enqueue() -> Response:
    event = app.current_event
    source_ip = event.request_context.http.source_ip
    claims = event.request_context.authorizer.jwt_claim
    principal = claims.get("sub")

    allowed_client_id = os.environ.get("ALLOWED_CLIENT_ID")
    if allowed_client_id is not None and principal != allowed_client_id:
        logger.warning(
            "Request denied by client ID allowlist",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "DENY"},
        )
        return Response(status_code=403, content_type="application/json", body=json.dumps({"message": "Forbidden"}))

    networks = parse_allowed_networks(os.environ.get("ALLOWED_IPS", ""))
    if not is_allowed(source_ip, networks):
        logger.warning(
            "Request denied by IP allowlist",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "DENY"},
        )
        return Response(status_code=403, content_type="application/json", body=json.dumps({"message": "Forbidden"}))

    try:
        result = get_sqs_client().send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=event.body or "")
    except ClientError:
        logger.exception(
            "Failed to enqueue message",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "ERROR"},
        )
        return Response(
            status_code=500,
            content_type="application/json",
            body=json.dumps({"message": "Internal Server Error"}),
        )

    logger.info(
        "Request allowed and enqueued",
        extra={
            "sourceIp": source_ip,
            "principal": principal,
            "decision": "ALLOW",
            "messageId": result["MessageId"],
        },
    )
    return Response(status_code=202, content_type="application/json", body=json.dumps({"message": "Accepted"}))


@logger.inject_lambda_context
def lambda_handler(event: dict[str, object], context: LambdaContext) -> dict[str, object]:
    return app.resolve(event, context)
```

Key changes from the old version:
- `APIGatewayProxyEventV2` / `@event_source` removed; event access is now via `app.current_event`
- `_build_response` helper removed; replaced with inline `Response(...)` calls
- `lambda_handler` parameter type changed from `APIGatewayProxyEventV2` to `dict[str, object]`
- `oauth_router` included at module level

- [ ] **Step 2: Update the one exact-dict assertion in `tests/test_producer.py`**

Find `test_handler_allowed_request_is_enqueued` and replace its response assertion. The `APIGatewayHttpResolver` may format the response dict differently (e.g. extra headers) compared to the hand-built dict from the old `_build_response`. Change from:

```python
assert response == {
    "statusCode": 202,
    "headers": {"content-type": "application/json"},
    "body": json.dumps({"message": "Accepted"}),
}
```

to:

```python
assert response["statusCode"] == 202
assert json.loads(response["body"]) == {"message": "Accepted"}
```

- [ ] **Step 3: Run the full test suite**

```bash
make test
```

Expected: all tests in `tests/test_producer.py`, `tests/test_oauth.py`, `tests/test_consumer.py`, and `tests/test_allowlist.py` pass; lint clean.

If any test fails, fix it before continuing. Common failure modes:
- `test_oauth.py` import error → check `app/oauth.py` exists and `app.include_router(oauth_router)` is present
- `test_producer.py` assertion mismatch → compare actual `response` dict keys/values and update the assertion accordingly

- [ ] **Step 4: Commit**

```bash
git add app/producer.py tests/test_producer.py
git commit -m "feat: refactor producer to APIGatewayHttpResolver, add oauth router"
```

---

## Task 4: Add `OAuthTokenRoute` to `aws/api-gateway.yml`

**Files:**
- Modify: `aws/api-gateway.yml`

**Interfaces:**
- Consumes: `ProducerIntegration` (existing resource in the same template)
- Produces: `POST /oauth/token` route with `AuthorizationType: NONE` in the deployed stack

- [ ] **Step 1: Add the new route resource**

In `aws/api-gateway.yml`, add `OAuthTokenRoute` in the `Resources` section, immediately after the existing `PostRoute` resource:

```yaml
  OAuthTokenRoute:
    Type: AWS::ApiGatewayV2::Route
    Properties:
      ApiId: !Ref HttpApi
      RouteKey: POST /oauth/token
      AuthorizationType: NONE
      Target: !Sub "integrations/${ProducerIntegration}"
```

No other changes needed — `ProducerInvokePermission` already uses `SourceArn: !Sub "arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${HttpApi}/*/*"` which covers all routes and methods.

- [ ] **Step 2: Run cfn-lint**

```bash
make cfn-lint
```

Expected: exit 0, no errors or warnings. Fix any reported issues.

- [ ] **Step 3: Commit**

```bash
git add aws/api-gateway.yml
git commit -m "feat: add POST /oauth/token route (AuthorizationType: NONE) to API Gateway"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| `POST /oauth/token` endpoint | Task 4 (CF route) + Task 3 (resolver) |
| Log headers and body | Task 2, `issue_token()` — `logger.info(... headers, body)` |
| Return access token response | Task 2, `issue_token()` — `Response(200, ..., body=json.dumps({...}))` |
| Signed JWT, Okta-style claims | Task 2, `issue_token()` — `jwt.encode(claims, ...)` with `iss/sub/cid/aud/iat/exp/scp` |
| `client_id` from body reflected | Task 2, `_parse_client_id()` |
| Missing `client_id` fallback | Task 2, `_parse_client_id()` returns `"mock-client"` |
| Hardcoded signing secret | Task 2, `_MOCK_SIGNING_SECRET` module constant |
| `MOCK_ISSUER` env var with default | Task 2, `os.environ.get("MOCK_ISSUER", _DEFAULT_ISSUER)` |
| No credential validation | Task 2 — no 401/403 path in `issue_token()` |
| `AuthorizationType: NONE` | Task 4 |
| Same Lambda / integration | Task 4 — reuses `ProducerIntegration` |
| `APIGatewayHttpResolver` in producer.py | Task 3 |
| `PyJWT` dependency | Task 1 |
| `POST /` still works with JWT auth | Task 3 — `_enqueue()` keeps all existing logic |
| Existing tests still pass | Task 3, Step 3 |

No gaps found.

**Placeholder scan:** No TBDs, TODOs, or vague steps present.

**Type consistency:** `router` defined in Task 2 as `Router`; imported as `oauth_router` in Task 3. `_MOCK_SIGNING_SECRET` defined in Task 2 as `str`; imported in test file for `jwt.decode`. `Response` used in both Task 2 and Task 3 — same import path `aws_lambda_powertools.event_handler.api_gateway`.
