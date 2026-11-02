"""The /api/assist agentic pipeline: PLAN -> LOCATE -> CHECK -> ZOOM -> READ.

Muse plans where to look, SAM 3.1 locates the panel (with one retry round),
the app checks the geometry and zooms in, and Muse reads the crops plus the
whole photo and reports its own status.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.imaging import crop_box, load_normalized, to_jpeg
from app.meta_api import (
    FRAMING_NOTES,
    MetaUpstreamError,
    parse_boxes,
    plan_question,
    read_label,
    segment_image,
)

logger = logging.getLogger(__name__)

# The noun phrases are first guesses. Keep them in this one place: the
# evaluation tunes them.
PRESET_PLANS = {
    "read": {
        "concepts": ["label"],
        "task": (
            "Read the main printed text on the label exactly as printed, "
            "starting with the product name."
        ),
    },
    "allergens": {
        "concepts": ["ingredients list", "label"],
        "task": (
            "Find the ingredients list and any allergen or 'may contain' "
            "statements, and report which allergens are printed."
        ),
    },
    "expiry": {
        "concepts": ["label", "lid"],
        "task": (
            "Find the expiry, use-by, or best-before date and read it exactly "
            "as printed, with its label."
        ),
    },
    "what": {
        "concepts": [],
        "task": (
            "Say briefly what the object is, using its printed product name "
            "if one is visible."
        ),
    },
}
FALLBACK_CONCEPTS = ["label", "text"]
FALLBACK_TASK = "Answer the user's question from the printed text."
ANSWER_LANGUAGES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "el": "Greek",
    "zh": "Simplified Chinese",
}
MAX_CONCEPTS_PER_ROUND = 2
MAX_ROUNDS = 2
MIN_CONFIDENCE = 0.5
MAX_CROPS = 2
EDGE_MARGIN = 0.01
MIN_AREA_FRACTION = 0.03
TOO_CLOSE_AREA_FRACTION = 0.9
SAM_MAX_EDGE = 2048
CROP_MAX_EDGE = 2048
CONTEXT_MAX_EDGE = 1280
FULL_ONLY_MAX_EDGE = 2048
PLAN_TIMEOUT_S = 20
SAM_TIMEOUT_S = 20


@dataclass
class AssistResult:
    answer_status: str
    answer: str
    evidence: str
    source: str  # "region" | "full"
    fallback: bool
    concept: str | None
    concepts_tried: list[str]
    boxes: list[dict[str, Any]]  # the crops used, best first, in SAM's frame
    framing: list[str]  # the CHECK codes
    timings_ms: dict[str, int]


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def sanitize_concepts(concepts: list[str]) -> list[str]:
    """Clean PLAN concepts into short SAM-ready noun phrases (at most 3)."""
    cleaned: list[str] = []
    for raw in concepts:
        text = " ".join(raw.strip().lower().split())
        for sep in (",", ";", "+", "\n"):
            text = text.split(sep, 1)[0]
        text = " ".join(text.split())
        text = " ".join(text.split(" ")[:4])
        if len(text) > 40:
            text = text[:40].rsplit(" ", 1)[0].strip()
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= 3:
            break
    return cleaned


def _is_usable(box: dict[str, Any]) -> bool:
    if box["x2"] <= box["x1"] or box["y2"] <= box["y1"]:
        return False
    if box["w"] <= 0 or box["h"] <= 0:
        return False
    confidence = box.get("c")
    return confidence is None or confidence >= MIN_CONFIDENCE


def _box_sort_key(box: dict[str, Any]) -> tuple[bool, float, int]:
    """Highest confidence (None last), then largest area."""
    confidence = box.get("c")
    area = (box["x2"] - box["x1"]) * (box["y2"] - box["y1"])
    return (confidence is None, -(confidence or 0.0), -area)


def _iou(first: dict[str, Any], second: dict[str, Any]) -> float:
    ix1 = max(first["x1"], second["x1"])
    iy1 = max(first["y1"], second["y1"])
    ix2 = min(first["x2"], second["x2"])
    iy2 = min(first["y2"], second["y2"])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_first = (first["x2"] - first["x1"]) * (first["y2"] - first["y1"])
    area_second = (second["x2"] - second["x1"]) * (second["y2"] - second["y1"])
    union = area_first + area_second - inter
    return inter / union if union > 0 else 0.0


def check_framing(primary_box: dict[str, Any] | None, tried_any: bool) -> list[str]:
    """Map the primary box geometry to framing codes (at most 2).

    The codes never stop the reading: they become READ framing notes and
    spoken tips.
    """
    if primary_box is None:
        return ["not_found"] if tried_any else []
    box = primary_box
    w, h = box["w"], box["h"]
    margin = EDGE_MARGIN
    left = box["x1"] <= margin * w
    right = box["x2"] >= (1 - margin) * w - 1
    top = box["y1"] <= margin * h
    bottom = box["y2"] >= (1 - margin) * h - 1
    area_fraction = (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]) / (w * h)
    codes: list[str] = []
    if (left and right) or (top and bottom) or area_fraction >= TOO_CLOSE_AREA_FRACTION:
        codes.append("too_close")
    else:
        if left:
            codes.append("cut_off_left")
        if right:
            codes.append("cut_off_right")
        if top:
            codes.append("cut_off_top")
        if bottom:
            codes.append("cut_off_bottom")
    if area_fraction < MIN_AREA_FRACTION:
        codes.append("too_small")
    return codes[:2]


async def run_assist(
    *,
    api_key: str,
    image_bytes: bytes,
    question: str,
    language: str,
    preset: str | None,
    client: httpx.AsyncClient | None = None,
    images_mode: str = "crop+full",
) -> AssistResult:
    """Run the assist pipeline and return the structured answer.

    ``images_mode`` is internal only, for the later evaluation script:
    "crop+full" (the default), "crop" (crops without the context image),
    or "full" (no SAM at all). Never exposed over HTTP.

    Raises:
        MetaUpstreamError: only the READ stage fails the request.
        ImageTooLargeError / ImageDecodeError: from normalization.
    """
    if images_mode not in ("crop+full", "crop", "full"):
        raise ValueError(f"Unknown images_mode: {images_mode}")
    started = time.perf_counter()
    timings_ms: dict[str, int] = {}
    tried: list[str] = []
    rounds = 0

    # Normalize once. SAM sees exactly this EXIF-free JPEG, so its w/h have
    # img's aspect ratio and boxes map to img directly.
    img = await asyncio.to_thread(load_normalized, image_bytes)
    sam_jpeg = await asyncio.to_thread(to_jpeg, img, SAM_MAX_EDGE, 90)

    # PLAN: presets are instant; free text asks Muse (text-only).
    plan_started = time.perf_counter()
    if preset is not None:
        concepts = list(PRESET_PLANS[preset]["concepts"])
        task = PRESET_PLANS[preset]["task"]
    else:
        try:
            plan = await plan_question(
                api_key, question, client=client, timeout=PLAN_TIMEOUT_S
            )
        except MetaUpstreamError as exc:
            logger.warning("Assist plan failed: error=%s", type(exc).__name__)
            concepts = FALLBACK_CONCEPTS[:1]
            task = FALLBACK_TASK
        else:
            concepts = sanitize_concepts(plan.concepts)
            task = plan.task
            if not concepts and plan.concepts:
                logger.warning(
                    "Assist plan concepts unusable: dropped=%d", len(plan.concepts)
                )
                concepts = FALLBACK_CONCEPTS[:1]
                task = FALLBACK_TASK
    timings_ms["plan"] = _ms(plan_started)

    # LOCATE: at most 2 rounds; a failed concept counts as "no boxes".
    async def locate_one(concept: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            output_text = await segment_image(
                api_key,
                sam_jpeg,
                "image/jpeg",
                concept,
                client=client,
                timeout=SAM_TIMEOUT_S,
            )
        except MetaUpstreamError as exc:
            logger.warning(
                "Assist SAM failed: service=Segmentation status=%s error=%s",
                exc.status_code,
                type(exc).__name__,
            )
            return concept, []
        return concept, parse_boxes(output_text)

    async def locate_round(round_concepts: list[str]) -> None:
        tried.extend(round_concepts)
        results = await asyncio.gather(
            *(locate_one(concept) for concept in round_concepts),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                continue
            concept, boxes = result
            boxes_by_concept[concept] = boxes

    locate_started = time.perf_counter()
    boxes_by_concept: dict[str, list[dict[str, Any]]] = {}
    if concepts and images_mode != "full":
        rounds = 1
        await locate_round(concepts[:MAX_CONCEPTS_PER_ROUND])
        usable_found = any(
            _is_usable(box) for boxes in boxes_by_concept.values() for box in boxes
        )
        if not usable_found and rounds < MAX_ROUNDS:
            candidates = [
                concept
                for concept in list(concepts) + FALLBACK_CONCEPTS
                if concept not in tried
            ]
            round_two: list[str] = []
            for concept in candidates:
                if concept not in round_two:
                    round_two.append(concept)
                if len(round_two) >= MAX_CONCEPTS_PER_ROUND:
                    break
            if round_two:
                rounds = 2
                await locate_round(round_two)
    timings_ms["locate"] = _ms(locate_started)

    # Choose boxes: plan order, then confidence, then area.
    def usable_sorted(concept: str) -> list[dict[str, Any]]:
        return sorted(
            (box for box in boxes_by_concept.get(concept, []) if _is_usable(box)),
            key=_box_sort_key,
        )

    primary_concept: str | None = None
    primary_box: dict[str, Any] | None = None
    for concept in tried:
        first_usable = usable_sorted(concept)
        if first_usable:
            primary_concept = concept
            primary_box = first_usable[0]
            break

    chosen: list[tuple[str, dict[str, Any]]] = []
    if primary_box is not None and primary_concept is not None:
        chosen.append((primary_concept, primary_box))
        if len(chosen) < MAX_CROPS:
            candidates: list[tuple[str, dict[str, Any]]] = []
            for concept in tried:
                if concept == primary_concept:
                    continue
                other_usable = usable_sorted(concept)
                if other_usable:
                    candidates.append((concept, other_usable[0]))
            own_usable = usable_sorted(primary_concept)
            if len(own_usable) > 1:
                candidates.append((primary_concept, own_usable[1]))
            for concept, box in candidates:
                if _iou(primary_box, box) < 0.5:
                    chosen.append((concept, box))
                    break

    # CHECK, then ZOOM.
    framing = check_framing(primary_box, bool(tried))
    crop_started = time.perf_counter()
    crops: list[tuple[str, bytes]] = []
    for concept, box in chosen:
        crop_img = await asyncio.to_thread(crop_box, img, box)
        crops.append(
            (concept, await asyncio.to_thread(to_jpeg, crop_img, CROP_MAX_EDGE, 90))
        )
    if images_mode == "crop":
        context_jpeg: bytes | None = None
    elif chosen:
        context_jpeg = await asyncio.to_thread(to_jpeg, img, CONTEXT_MAX_EDGE, 85)
    else:
        context_jpeg = await asyncio.to_thread(to_jpeg, img, FULL_ONLY_MAX_EDGE, 90)
    timings_ms["crop"] = _ms(crop_started)

    # READ: the only stage whose failure fails the request.
    read_started = time.perf_counter()
    label = await read_label(
        api_key,
        question=question,
        task=task,
        language_name=ANSWER_LANGUAGES[language],
        framing_notes=[FRAMING_NOTES[code] for code in framing],
        crops=crops,
        context_jpeg=context_jpeg,
        client=client,
    )
    timings_ms["read"] = _ms(read_started)
    timings_ms["total"] = _ms(started)

    source = "region" if chosen else "full"
    logger.info(
        "Assist: preset=%s plan_ms=%d locate_ms=%d crop_ms=%d read_ms=%d "
        "total_ms=%d rounds=%d sam_calls=%d concept=%s source=%s answer_status=%s",
        preset or "free",
        timings_ms["plan"],
        timings_ms["locate"],
        timings_ms["crop"],
        timings_ms["read"],
        timings_ms["total"],
        rounds,
        len(tried),
        primary_concept or "-",
        source,
        label.status,
    )
    return AssistResult(
        answer_status=label.status,
        answer=label.answer,
        evidence=label.evidence,
        source=source,
        fallback=bool(tried) and not chosen,
        concept=primary_concept,
        concepts_tried=tried,
        boxes=[box for _, box in chosen],
        framing=framing,
        timings_ms=timings_ms,
    )
