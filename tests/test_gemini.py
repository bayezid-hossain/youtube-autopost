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
