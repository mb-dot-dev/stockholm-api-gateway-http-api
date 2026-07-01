from __future__ import annotations

import json
from typing import TYPE_CHECKING

import jwt

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
