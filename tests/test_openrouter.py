import json

import httpx
import pytest

from actionreplay.discovery import OpenRouterClient, check_openrouter_response, safe_error_details
from actionreplay.policy import AutomationError


def test_openrouter_http_diagnostics_exclude_response_body():
    request = httpx.Request("GET", "https://openrouter.ai/api/v1/models")
    response = httpx.Response(401, request=request, text="secret provider response")
    error = httpx.HTTPStatusError("unsafe message", request=request, response=response)
    assert safe_error_details(error) == {
        "error_type": "HTTPStatusError",
        "http_status": 401,
        "endpoint": "/api/v1/models",
    }
    with pytest.raises(AutomationError, match="OPENROUTER_NO_PROVIDER") as raised:
        check_openrouter_response(httpx.Response(404, request=request, text="secret provider response"))
    assert raised.value.details["http_status"] == 404
    assert "secret provider response" not in str(raised.value.details)


async def test_openrouter_multimodal_protocol():
    requests = []

    def transport(request):
        requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "test/model",
                            "architecture": {"input_modalities": ["text", "image"]},
                            "supported_parameters": ["tools", "tool_choice"],
                        }
                    ]
                },
            )
        body = json.loads(request.content)
        assert body["provider"]["require_parameters"] is True
        assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "parallel_tool_calls" not in body
        assert "Capability" not in body["tools"][0]["function"]["parameters"].get("title", "")
        decision = {"kind": "action", "step": {"id": "click", "action": "click", "target": "e1"}}
        return httpx.Response(
            200,
            json={
                "id": "request-1",
                "model": "test/model",
                "usage": {"total_tokens": 42},
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": "perform", "arguments": json.dumps(decision)}}
                            ]
                        }
                    }
                ],
            },
        )

    client = OpenRouterClient(api_key="synthetic-test-key", model="test/model")
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(transport)
    )
    try:
        details = await client.validate()
        assert details == {
            "model": "test/model",
            "model_found": True,
            "image_input": True,
            "tool_calling": True,
            "tool_choice": True,
        }
        decision, metadata = await client.decide(
            "A user goal", {}, {"frames": [], "screenshot": "AA=="}, [], {}
        )
        assert decision.step.action == "click"
        assert metadata["usage"] == {"total_tokens": 42}
        assert len(requests) == 2
    finally:
        await client.close()


@pytest.mark.parametrize(
    "modalities,params",
    [
        (["text"], ["tools", "tool_choice"]),
        (["text", "image"], []),
        (["text", "image"], ["tools"]),
    ],
)
async def test_model_feature_preflight(modalities, params):
    client = OpenRouterClient(api_key="synthetic-test-key", model="test/model")
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "test/model",
                            "architecture": {"input_modalities": modalities},
                            "supported_parameters": params,
                        }
                    ]
                },
            )
        ),
    )
    try:
        with pytest.raises(AutomationError, match="MODEL_REQUIRES_IMAGE_AND_TOOLS") as raised:
            await client.validate()
        assert raised.value.details["model_found"] is True
        assert raised.value.details["image_input"] is ("image" in modalities)
        assert raised.value.details["tool_calling"] is ("tools" in params)
        assert raised.value.details["tool_choice"] is ("tool_choice" in params)
    finally:
        await client.close()


async def test_invalid_finish_decision_reports_schema_details():
    def transport(request):
        return httpx.Response(
            200,
            json={
                "id": "request-bad",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "perform",
                                        "arguments": json.dumps({"kind": "finish", "success": []}),
                                    }
                                }
                            ]
                        }
                    }
                ],
            },
        )

    client = OpenRouterClient(api_key="synthetic-test-key", model="test/model")
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(transport)
    )
    try:
        with pytest.raises(AutomationError, match="MODEL_DECISION_SCHEMA_INVALID") as raised:
            await client.decide("goal", {}, {"frames": [], "screenshot": "AA=="}, [], {})
        assert raised.value.details["validation_error_count"] >= 1
        assert raised.value.details["validation_errors"]
    finally:
        await client.close()
