import asyncio
import io
from typing import Any

import pytest
from PIL import Image

from app.meta_api import LabelAnswer, LookPlan, MetaUpstreamError
from app.pipeline import (
    ANSWER_LANGUAGES,
    PRESET_PLANS,
    check_framing,
    run_assist,
    sanitize_concepts,
)


def _photo_bytes(width: int = 200, height: int = 200) -> bytes:
    img = Image.new("RGB", (width, height), color=(10, 200, 10))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


PHOTO = _photo_bytes()


def _box(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    w: int = 100,
    h: int = 100,
    c: float | None = None,
) -> str:
    token = f"<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={w};h={h}"
    if c is not None:
        token += f";c={c}"
    return token + "|>"


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: LookPlan | Exception | None = None,
    segments: dict[str, str | Exception] | None = None,
    answer: LabelAnswer | None = None,
) -> dict[str, Any]:
    calls: dict[str, Any] = {"plan": 0, "segments": [], "read": None}

    async def fake_plan(api_key: str, question: str, **kwargs: Any) -> LookPlan:
        calls["plan"] += 1
        if isinstance(plan, Exception):
            raise plan
        assert plan is not None
        return plan

    async def fake_segment(
        api_key: str,
        image_bytes: bytes,
        media_type: str,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        calls["segments"].append(prompt)
        outcome = (segments or {}).get(prompt, "")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def fake_read(api_key: str, **kwargs: Any) -> LabelAnswer:
        calls["read"] = kwargs
        return answer or LabelAnswer(status="answered", answer="A.", evidence="E.")

    monkeypatch.setattr("app.pipeline.plan_question", fake_plan)
    monkeypatch.setattr("app.pipeline.segment_image", fake_segment)
    monkeypatch.setattr("app.pipeline.read_label", fake_read)
    return calls


def _run(**kwargs: Any) -> Any:
    params: dict[str, Any] = {
        "api_key": "test-key",
        "image_bytes": PHOTO,
        "question": "What is this?",
        "language": "en",
        "preset": None,
    }
    params.update(kwargs)
    return asyncio.run(run_assist(**params))


def test_preset_skips_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fakes(
        monkeypatch,
        segments={"ingredients list": _box(10, 10, 50, 50), "label": ""},
    )
    result = _run(preset="allergens")
    assert calls["plan"] == 0
    assert result.concepts_tried == ["ingredients list", "label"]
    assert result.concept == "ingredients list"
    assert result.source == "region"
    assert result.fallback is False
    assert result.boxes[0]["x1"] == 10
    assert result.framing == []
    assert calls["read"]["task"].startswith("Find the ingredients list")
    assert set(result.timings_ms) == {"plan", "locate", "crop", "read", "total"}


def test_free_text_calls_plan_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fakes(
        monkeypatch,
        plan=LookPlan(concepts=["label"], task="Read the label."),
        segments={"label": _box(10, 10, 50, 50)},
    )
    result = _run()
    assert calls["plan"] == 1
    assert calls["read"]["task"] == "Read the label."
    assert result.source == "region"


def test_plan_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fakes(
        monkeypatch, plan=MetaUpstreamError(502, "Question answering failed.")
    )
    result = _run()
    assert result.source == "full"
    assert result.fallback is True
    assert result.concepts_tried == ["label", "text"]
    assert result.boxes == []
    assert result.framing == ["not_found"]
    assert calls["read"]["crops"] == []
    assert calls["read"]["context_jpeg"] is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["  Ingredients List "], ["ingredients list"]),
        (["label, text"], ["label"]),
        (["a;b"], ["a"]),
        (["one+two"], ["one"]),
        (["a b c d e f"], ["a b c d"]),
        (["x" * 50], ["x" * 40]),
        (["label", "Label", "label "], ["label"]),
        (["a", "b", "c", "d"], ["a", "b", "c"]),
        ([""], []),
        ([",,,"], []),
    ],
)
def test_sanitize_concepts(raw: list[str], expected: list[str]) -> None:
    assert sanitize_concepts(raw) == expected


def test_plan_concepts_all_dropped_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fakes(
        monkeypatch, plan=LookPlan(concepts=[",,,"], task="Read it.")
    )
    result = _run()
    assert result.concepts_tried == ["label", "text"]
    assert calls["read"]["task"] == "Answer the user's question from the printed text."


def test_empty_plan_skips_locate(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fakes(
        monkeypatch, plan=LookPlan(concepts=[], task="Say what it is.")
    )
    result = _run()
    assert calls["segments"] == []
    assert result.concepts_tried == []
    assert result.source == "full"
    assert result.fallback is False
    assert result.framing == []


def test_locate_runs_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []
    both_started = asyncio.Event()

    async def fake_plan(api_key: str, question: str, **kwargs: Any) -> LookPlan:
        return LookPlan(concepts=["aaa", "bbb"], task="T.")

    async def fake_segment(
        api_key: str,
        image_bytes: bytes,
        media_type: str,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        started.append(prompt)
        if len(started) >= 2:
            both_started.set()
        # Sequential execution would deadlock here; wait_for fails it loudly.
        await both_started.wait()
        return ""

    async def fake_read(api_key: str, **kwargs: Any) -> LabelAnswer:
        return LabelAnswer(status="answered", answer="A.", evidence="")

    monkeypatch.setattr("app.pipeline.plan_question", fake_plan)
    monkeypatch.setattr("app.pipeline.segment_image", fake_segment)
    monkeypatch.setattr("app.pipeline.read_label", fake_read)
    result = asyncio.run(
        asyncio.wait_for(
            run_assist(
                api_key="k",
                image_bytes=PHOTO,
                question="Q?",
                language="en",
                preset=None,
            ),
            timeout=5,
        )
    )
    assert sorted(started[:2]) == ["aaa", "bbb"]
    assert result.source == "full"


def test_round_two_runs_after_empty_round_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fakes(
        monkeypatch, plan=LookPlan(concepts=["aaa", "bbb"], task="T.")
    )
    result = _run()
    assert calls["segments"] == ["aaa", "bbb", "label", "text"]
    assert result.concepts_tried == ["aaa", "bbb", "label", "text"]
    assert result.fallback is True


def test_no_round_two_when_round_one_finds_box(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fakes(
        monkeypatch,
        segments={"ingredients list": _box(10, 10, 50, 50), "label": ""},
    )
    _run(preset="allergens")
    assert calls["segments"] == ["ingredients list", "label"]


def test_never_more_than_two_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fakes(
        monkeypatch, plan=LookPlan(concepts=["aaa", "bbb", "ccc"], task="T.")
    )
    _run()
    assert calls["segments"] == ["aaa", "bbb", "ccc", "label"]
    assert "text" not in calls["segments"]


def test_sam_exception_counts_as_no_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fakes(
        monkeypatch,
        plan=LookPlan(concepts=["aaa", "bbb"], task="T."),
        segments={
            "aaa": MetaUpstreamError(502, "Segmentation failed."),
            "bbb": _box(10, 10, 50, 50),
        },
    )
    result = _run()
    assert calls["segments"] == ["aaa", "bbb"]
    assert result.source == "region"
    assert result.concept == "bbb"


def test_primary_box_priority_confidence_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fakes(
        monkeypatch,
        plan=LookPlan(concepts=["aaa", "bbb"], task="T."),
        segments={
            "aaa": _box(10, 10, 20, 20, c=0.6) + _box(30, 30, 80, 80, c=0.6),
            "bbb": _box(0, 0, 90, 90, c=0.99),
        },
    )
    result = _run()
    assert calls["segments"] == ["aaa", "bbb"]
    assert result.concept == "aaa"
    assert result.boxes[0]["x1"] == 30
    # Second crop: the best box of the next concept.
    assert len(result.boxes) == 2
    assert result.boxes[1]["x2"] == 90


def test_box_confidence_ordering_and_second_best(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(
        monkeypatch,
        plan=LookPlan(concepts=["aaa"], task="T."),
        segments={"aaa": _box(10, 10, 20, 20) + _box(30, 30, 40, 40, c=0.5)},
    )
    result = _run()
    assert result.boxes[0]["c"] == 0.5
    assert result.boxes[1]["c"] is None


def test_low_confidence_boxes_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fakes(
        monkeypatch,
        plan=LookPlan(concepts=["aaa"], task="T."),
        segments={"aaa": _box(10, 10, 50, 50, c=0.4)},
    )
    result = _run()
    assert result.source == "full"
    assert result.fallback is True
    assert result.framing == ["not_found"]


def test_overlapping_second_box_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fakes(
        monkeypatch,
        plan=LookPlan(concepts=["aaa"], task="T."),
        segments={"aaa": _box(10, 10, 50, 50) + _box(12, 12, 48, 48)},
    )
    result = _run()
    assert len(result.boxes) == 1


def _frame_box(x1: int, y1: int, x2: int, y2: int) -> dict[str, int]:
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "w": 100, "h": 100}


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        (_frame_box(30, 30, 70, 70), []),
        (_frame_box(0, 30, 40, 70), ["cut_off_left"]),
        (_frame_box(60, 30, 99, 70), ["cut_off_right"]),
        (_frame_box(30, 0, 70, 40), ["cut_off_top"]),
        (_frame_box(30, 60, 70, 99), ["cut_off_bottom"]),
        (_frame_box(0, 30, 99, 70), ["too_close"]),
        (_frame_box(30, 0, 70, 99), ["too_close"]),
        (_frame_box(2, 2, 97, 97), ["too_close"]),
        (_frame_box(30, 30, 40, 40), ["too_small"]),
        (_frame_box(0, 30, 10, 40), ["cut_off_left", "too_small"]),
        (_frame_box(0, 0, 40, 40), ["cut_off_left", "cut_off_top"]),
        (_frame_box(0, 0, 10, 10), ["cut_off_left", "cut_off_top"]),
    ],
)
def test_check_framing_codes(box: dict[str, int], expected: list[str]) -> None:
    assert check_framing(box, True) == expected


def test_check_framing_not_found() -> None:
    assert check_framing(None, True) == ["not_found"]
    assert check_framing(None, False) == []


def test_images_mode_full_skips_sam(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fakes(
        monkeypatch, plan=LookPlan(concepts=["label"], task="Read it.")
    )
    result = _run(images_mode="full")
    assert calls["segments"] == []
    assert result.concepts_tried == []
    assert result.source == "full"
    assert result.fallback is False


def test_images_mode_crop_omits_context(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fakes(
        monkeypatch,
        segments={"label": _box(10, 10, 50, 50)},
    )
    result = _run(preset="read", images_mode="crop")
    assert result.source == "region"
    assert len(calls["read"]["crops"]) == 1
    assert calls["read"]["context_jpeg"] is None


def test_images_mode_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fakes(monkeypatch, plan=LookPlan(concepts=[], task="T."))
    with pytest.raises(ValueError, match="images_mode"):
        _run(images_mode="bogus")


def test_preset_and_language_tables() -> None:
    assert set(PRESET_PLANS) == {"read", "allergens", "expiry", "what"}
    for plan in PRESET_PLANS.values():
        assert set(plan) == {"concepts", "task"}
    assert set(ANSWER_LANGUAGES) == {"en", "fr", "es", "el", "zh"}
