from uuid import uuid4

from generation.domain.enums import FailureType
from generation.domain.rules import LegView, choose_next_leg


def _leg(
    priority: int,
    *,
    max_ref_images: int = 4,
    skip_on_moderation: bool = False,
) -> LegView:
    return LegView(
        id=uuid4(),
        provider=f"p{priority}",
        priority=priority,
        max_ref_images=max_ref_images,
        skip_on_moderation=skip_on_moderation,
    )


def test_first_leg_that_accepts_refs() -> None:
    tight, wide = _leg(1, max_ref_images=1), _leg(2, max_ref_images=10)
    chosen = choose_next_leg(
        [tight, wide],
        ref_image_count=2,
        used_leg_ids=set(),
        previous_failure=None,
    )
    assert chosen is wide


def test_skip_used_and_moderation_flag() -> None:
    first = _leg(1)
    second = _leg(2, skip_on_moderation=True)
    third = _leg(3)
    chosen = choose_next_leg(
        [first, second, third],
        ref_image_count=0,
        used_leg_ids={first.id},
        previous_failure=FailureType.MODERATION,
    )
    assert chosen is third


def test_payload_never_continues() -> None:
    chosen = choose_next_leg(
        [_leg(1), _leg(2)],
        ref_image_count=0,
        used_leg_ids=set(),
        previous_failure=FailureType.PAYLOAD,
    )
    assert chosen is None
