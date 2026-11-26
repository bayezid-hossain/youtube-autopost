from types import SimpleNamespace

import pytest

from autopost.gemini import make_gemini


class FakeModels:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(text=self.text)


def client_returning(text):
    return SimpleNamespace(models=FakeModels(text))


def test_generator_parses_json_response():
    client = client_returning('{"title": "Cake", "description": "Yum", "tags": ["cake"]}')
    generate = make_gemini(client, "gemini-flash-latest", "Cooking channel")
    assert generate("best_cake", "short") == {"title": "Cake", "description": "Yum", "tags": ["cake"]}

    call = client.models.calls[0]
    assert call["model"] == "gemini-flash-latest"
    assert "best_cake" in call["contents"]
    assert "Short" in call["contents"]
    assert "Cooking channel" in call["contents"]
    assert call["config"] == {"response_mime_type": "application/json"}


def test_generator_raises_on_bad_json():
    generate = make_gemini(client_returning("sorry, no"), "m", "")
    with pytest.raises(ValueError):
        generate("cake", "video")


def test_generator_raises_on_empty_response():
    generate = make_gemini(client_returning(None), "m", "")
    with pytest.raises(ValueError, match="empty Gemini response"):
        generate("cake", "video")


class FlakyModels:
    """Fails for the given models (or the first N calls), then returns JSON."""

    def __init__(self, fail_models=(), fail_first=0):
        self.fail_models = set(fail_models)
        self.fail_first = fail_first
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        if model in self.fail_models or len(self.calls) <= self.fail_first:
            raise RuntimeError("503 UNAVAILABLE")
        return SimpleNamespace(text='{"title": "T"}')


def test_generator_retries_transient_error_on_same_model():
    models = FlakyModels(fail_first=1)
    sleeps = []
    generate = make_gemini(SimpleNamespace(models=models), "main", "", fallbacks=("backup",), sleep=sleeps.append)
    assert generate("cake", "video") == {"title": "T"}
    assert models.calls == ["main", "main"]
    assert sleeps == [5]


def test_generator_falls_back_to_next_model():
    models = FlakyModels(fail_models={"main"})
    generate = make_gemini(SimpleNamespace(models=models), "main", "", fallbacks=("backup",), sleep=lambda s: None)
    assert generate("cake", "video") == {"title": "T"}
    assert models.calls == ["main", "main", "backup"]


def test_generator_raises_last_error_when_all_models_fail():
    models = FlakyModels(fail_models={"main", "backup"})
    generate = make_gemini(SimpleNamespace(models=models), "main", "", fallbacks=("backup",), sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="503"):
        generate("cake", "video")
    assert models.calls == ["main", "main", "backup", "backup"]


def test_generator_skips_fallback_equal_to_main_model():
    models = FlakyModels(fail_models={"main"})
    generate = make_gemini(SimpleNamespace(models=models), "main", "", fallbacks=("main",), sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        generate("cake", "video")
    assert models.calls == ["main", "main"]
