"""A scripted stand-in for the OpenAI client. No network, no tokens spent."""

from __future__ import annotations

import types
from typing import Any, Iterable


class FakeUsage:
    def __init__(
        self,
        input_tokens: int = 1000,
        cached_tokens: int = 0,
        output_tokens: int = 500,
        reasoning_tokens: int | None = 400,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens
        self.input_tokens_details = types.SimpleNamespace(cached_tokens=cached_tokens)
        self.output_tokens_details = types.SimpleNamespace(
            reasoning_tokens=reasoning_tokens
        )

    def model_dump(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "input_tokens_details": {
                "cached_tokens": self.input_tokens_details.cached_tokens
            },
            "output_tokens": self.output_tokens,
            "output_tokens_details": {
                "reasoning_tokens": self.output_tokens_details.reasoning_tokens
            },
            "total_tokens": self.total_tokens,
        }


class FakeResponse:
    _counter = 0

    def __init__(
        self,
        text: str,
        *,
        usage: FakeUsage | None = None,
        status: str = "completed",
        incomplete_details: Any = None,
        model: str = "gpt-6-astra",
    ) -> None:
        FakeResponse._counter += 1
        self.id = f"resp_fake_{FakeResponse._counter:04d}"
        self.output_text = text
        self.status = status
        self.incomplete_details = incomplete_details
        self.model = model
        self.service_tier = "default"
        self.usage = usage or FakeUsage()


class FakeClient:
    """Replays a script of responses and exceptions, recording every request."""

    def __init__(self, script: Iterable[Any]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []
        self.responses = _Responses(self)
        self.models = _Models()

    @property
    def calls(self) -> int:
        return len(self.requests)


class _Responses:
    def __init__(self, client: FakeClient) -> None:
        self._client = client

    def create(self, **kwargs: Any) -> Any:
        self._client.requests.append(kwargs)
        if not self._client.script:
            raise AssertionError("the fake client ran out of scripted responses")
        item = self._client.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item) and not isinstance(item, FakeResponse):
            return item(**kwargs)
        return item


class _Models:
    def retrieve(self, model: str) -> Any:
        return types.SimpleNamespace(id=model)


def moves(*sans: str, **usage_kwargs: Any) -> list[FakeResponse]:
    return [FakeResponse(san, usage=FakeUsage(**usage_kwargs)) for san in sans]
