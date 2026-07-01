# Mock OAuth Token Endpoint — Design

**Date:** 2026-07-01  
**Status:** Approved

## Summary

Add a second route (`POST /oauth/token`) to the existing API Gateway HTTP API that simulates Okta's OAuth 2.0 client-credentials token endpoint. The endpoint logs request headers and body, then returns a signed JWT in the standard Okta token response shape. Both routes are served by the existing producer Lambda, refactored to use `APIGatewayHttpResolver`.

---

## Architecture & Routing

The producer Lambda gains a module-level `APIGatewayHttpResolver` instance. `lambda_handler` delegates to it unconditionally. Two routes are registered:

| Route | Handler | API Gateway AuthorizationType |
|---|---|---|
| `POST /` | `_enqueue()` | JWT (existing) |
| `POST /oauth/token` | `issue_token()` | NONE (new) |

`@logger.inject_lambda_context` stays on the top-level `lambda_handler`. Each route handler returns a plain `dict`; the resolver handles HTTP response serialization.

---

## Files Changed

### `app/producer.py` — refactored

- Replace `@event_source(data_class=APIGatewayProxyEventV2)` with `APIGatewayHttpResolver`.
- Register existing enqueue logic as `@app.post("/")`.
- Register `issue_token` from `app/oauth.py` as `@app.post("/oauth/token")`.
- `lambda_handler` becomes `return app.resolve(event, context)`.

### `app/oauth.py` — new

Single public handler `issue_token()` registered on the resolver:

1. Log all request headers and raw body at INFO using the shared Powertools `Logger`.
2. Parse `client_id` from the form-encoded or JSON request body; fall back to `"mock-client"` if absent.
3. Build Okta-style JWT claims:
   - `iss`: value of `MOCK_ISSUER` env var, default `"https://mock-okta.example.com/oauth2/default"`
   - `sub` / `cid`: `client_id` from request body
   - `aud`: `"api://default"`
   - `iat`: current UTC time
   - `exp`: `iat + 3600`
   - `scp`: `["openid"]`
4. Sign with HS256 using a hardcoded secret (clearly marked mock-only in the code).
5. Return:

```json
{
  "access_token": "<signed JWT>",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scope": "openid"
}
```

### `aws/api-gateway.yml` — new route resource

```yaml
OAuthTokenRoute:
  Type: AWS::ApiGatewayV2::Route
  Properties:
    ApiId: !Ref HttpApi
    RouteKey: POST /oauth/token
    AuthorizationType: NONE
    Target: !Sub "integrations/${ProducerIntegration}"
```

No new integration, IAM role, or Lambda is needed. The existing `ProducerInvokePermission` uses a wildcard source ARN (`*/*/*`) and already covers the new route.

### `pyproject.toml` — new dependency

`PyJWT>=2.0` added to `[project.dependencies]`. `uv.lock` updated accordingly.

---

## Testing

### `tests/test_producer.py` — verify compatibility

Existing tests use a top-level `routeKey: "POST /"` field in their event dicts, which `APIGatewayHttpResolver` reads correctly. No structural changes expected; confirm tests pass after the refactor.

### `tests/test_oauth.py` — new

| Test | Assertion |
|---|---|
| Happy path | 200, response contains `access_token`, `token_type`, `expires_in`, `scope` |
| JWT claims | Decoded token has correct `iss`, `aud`, `exp`, `sub`/`cid` |
| `client_id` reflected | `sub`/`cid` in JWT matches `client_id` from request body |
| Missing `client_id` | Falls back to `"mock-client"` |
| Logging | Headers and body are logged at INFO level |

---

## Infrastructure Notes

- `producer-template.yaml`: no changes (same handler entrypoint `app.producer.lambda_handler`).
- CI/CD: no new jobs. Existing `deploy-api-gateway` job redeploys `aws/api-gateway.yml` and picks up `OAuthTokenRoute` automatically.
- The `POST /oauth/token` route is intentionally unauthenticated — it is the token-issuance endpoint.
