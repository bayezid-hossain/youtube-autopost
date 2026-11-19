import pytest

from autopost.metadata import (
    build_metadata,
    clean_title,
    finalize,
    parse_sidecar,
    pick_sidecar,
)
from autopost.models import DriveFile


def f(name):
    return DriveFile(id=name, name=name, created_time="t")


# --- parse_sidecar ---

def test_json_sidecar_full():
    text = '{"title": " Cake ", "description": "Easy cake", "tags": ["cake", " ", 3]}'
    assert parse_sidecar("a.json", text) == {
        "title": "Cake",
        "description": "Easy cake",
        "tags": ["cake"],
    }


def test_json_sidecar_partial():
    assert parse_sidecar("a.json", '{"title": "Cake"}') == {"title": "Cake"}


@pytest.mark.parametrize("text", ["not json", "[1, 2]"])
def test_json_sidecar_malformed_raises(text):
    with pytest.raises(ValueError):
        parse_sidecar("a.json", text)


def test_txt_sidecar_title_and_description():
    assert parse_sidecar("a.txt", "Cake\nLine one\nLine two\n") == {
        "title": "Cake",
        "description": "Line one\nLine two",
    }


def test_txt_sidecar_title_only():
    assert parse_sidecar("a.txt", "Cake\n") == {"title": "Cake"}


def test_txt_sidecar_empty():
    assert parse_sidecar("a.txt", "  \n") == {}


# --- pick_sidecar / clean_title ---

def test_pick_sidecar_prefers_json():
    assert pick_sidecar([f("a.txt"), f("a.json")]).name == "a.json"
    assert pick_sidecar([f("a.txt")]).name == "a.txt"
    assert pick_sidecar([]) is None


def test_clean_title():
    assert clean_title("my_best-cake__recipe.v2") == "my best cake recipe v2"


# --- finalize ---

def test_finalize_strips_angle_brackets_and_truncates_title():
    meta = finalize({"title": "<b>" + "x" * 200, "description": "a<b>c", "tags": []}, "video")
    assert meta.title == "b" + "x" * 99
    assert meta.description == "abc"


def test_finalize_adds_shorts_tag_only_to_shorts():
    assert finalize({"title": "t", "description": "d", "tags": []}, "short").description == "d\n\n#Shorts"
    assert finalize({"title": "t", "description": "d #shorts", "tags": []}, "short").description == "d #shorts"
    assert finalize({"title": "t", "description": "d", "tags": []}, "video").description == "d"


def test_finalize_keeps_shorts_tag_when_description_too_long():
    meta = finalize({"title": "t", "description": "x" * 6000, "tags": []}, "short")
    assert len(meta.description) <= 5000
    assert meta.description.endswith("#Shorts")


def test_finalize_fits_tags_into_500_chars():
    tags = ["a" * 100] * 10  # duplicates removed → one tag
    assert finalize({"title": "t", "description": "", "tags": tags}, "video").tags == ("a" * 100,)
    many = [f"tag{i:03d}" + "x" * 40 for i in range(20)]  # 46 chars each
    kept = finalize({"title": "t", "description": "", "tags": many}, "video").tags
    assert sum(len(t) for t in kept) + len(kept) - 1 <= 500
    assert len(kept) == 10


def test_finalize_empty_title_becomes_untitled():
    assert finalize({"title": "<>", "description": "", "tags": []}, "video").title == "Untitled"


# --- build_metadata ---

def test_full_sidecar_skips_generator(cfg):
    def generate(stem, kind):
        raise AssertionError("generator must not be called")

    sidecar = ("cake.json", '{"title": "T", "description": "D", "tags": ["x"]}')
    meta = build_metadata("cake", "video", sidecar, generate, cfg)
    assert (meta.title, meta.description, meta.tags) == ("T", "D", ("x",))


def test_generator_fills_missing_fields(cfg):
    calls = []

    def generate(stem, kind):
        calls.append((stem, kind))
        return {"title": "AI title", "description": "AI desc", "tags": ["ai"]}

    meta = build_metadata("cake", "short", ("cake.txt", "My title"), generate, cfg)
    assert calls == [("cake", "short")]
    assert meta.title == "My title"
    assert meta.description == "AI desc\n\n#Shorts"
    assert meta.tags == ("ai",)


def test_generator_failure_uses_fallback(cfg):
    def generate(stem, kind):
        raise RuntimeError("rate limited")

    meta = build_metadata("best_cake", "video", None, generate, cfg)
    assert meta.title == "best cake"
    assert meta.description == "Channel about home cooking."
    assert meta.tags == ("cooking", "recipes")


def test_malformed_sidecar_falls_through_to_generator(cfg):
    def generate(stem, kind):
        return {"title": "AI", "description": "AI", "tags": []}

    meta = build_metadata("cake", "video", ("cake.json", "{broken"), generate, cfg)
    assert meta.title == "AI"


def test_no_generator_uses_fallback(cfg):
    meta = build_metadata("cake", "video", None, None, cfg)
    assert meta.title == "cake"


def test_finalize_description_limit_is_bytes_for_video():
    meta = finalize({"title": "t", "description": "আ" * 3000, "tags": []}, "video")
    assert len(meta.description.encode()) <= 5000


def test_finalize_description_limit_is_bytes_for_short():
    meta = finalize({"title": "t", "description": "আ" * 3000, "tags": []}, "short")
    assert len(meta.description.encode()) <= 5000
    assert meta.description.endswith("#Shorts")
