"""The OpenRouter free router picks a different free model on every call and some of them
occasionally return no text. Every AI feature goes through OpenRouterLLMClient.create_message,
so that is where an empty reply must be retried instead of crashing."""
from types import SimpleNamespace

import pytest

from llm_providers import EmptyModelReply, OpenRouterLLMClient


def _reply(content, finish="stop", model="some/free-model:free"):
    return SimpleNamespace(model=model, choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))])


class _FakeCompletions:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


def _client(replies):
    completions = _FakeCompletions(replies)
    client = object.__new__(OpenRouterLLMClient)          # skip __init__: no API key needed
    client.model = "openrouter/free"
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def test_returns_the_stripped_text():
    client, completions = _client([_reply("  OK \n")])
    assert client.create_message([{"role": "user", "content": "hi"}], max_tokens=50) == "OK"
    assert completions.calls[0]["model"] == "openrouter/free" and completions.calls[0]["max_tokens"] == 50


def test_retries_when_a_free_model_returns_no_content():
    client, completions = _client([_reply(None), _reply("   "), _reply("OK")])
    assert client.create_message([{"role": "user", "content": "hi"}]) == "OK"
    assert len(completions.calls) == 3


def test_retries_when_the_response_has_no_choices():
    client, completions = _client([SimpleNamespace(model="x", choices=None), SimpleNamespace(model="x", choices=[]), _reply("OK")])
    assert client.create_message([{"role": "user", "content": "hi"}]) == "OK"
    assert len(completions.calls) == 3


def test_gives_up_with_a_clear_error_after_three_empty_replies():
    client, completions = _client([_reply(None, finish="length")] * 3)
    with pytest.raises(EmptyModelReply, match="no text"):
        client.create_message([{"role": "user", "content": "hi"}])
    assert len(completions.calls) == 3


def test_other_errors_are_not_swallowed_or_retried_here():
    client, completions = _client([])
    completions.create = lambda **kw: (_ for _ in ()).throw(RuntimeError("Error code: 402 - insufficient credits"))
    with pytest.raises(RuntimeError, match="402"):
        client.create_message([{"role": "user", "content": "hi"}])


def test_asks_reasoning_models_to_think_briefly_by_default():
    """Free reasoning models can spend the whole max_tokens on hidden thinking and return nothing."""
    client, completions = _client([_reply("OK")])
    client.create_message([{"role": "user", "content": "hi"}])
    assert completions.calls[0]["extra_body"] == {"reasoning": {"effort": "low"}}


def test_a_callers_own_extra_body_wins():
    client, completions = _client([_reply("OK")])
    client.create_message([{"role": "user", "content": "hi"}], extra_body={"reasoning": {"effort": "high"}})
    assert completions.calls[0]["extra_body"] == {"reasoning": {"effort": "high"}}
