from collections.abc import Sequence

from generation.domain.enums import FailureType


class LegView:
    """Minimal leg shape used by routing rules. Avoids leaking ORM into domain."""

    def __init__(
        self,
        *,
        id: object,
        provider: str,
        priority: int,
        max_ref_images: int,
        skip_on_moderation: bool,
    ) -> None:
        self.id = id
        self.provider = provider
        self.priority = priority
        self.max_ref_images = max_ref_images
        self.skip_on_moderation = skip_on_moderation


def choose_next_leg(
    legs: Sequence[LegView],
    *,
    ref_image_count: int,
    used_leg_ids: set[object],
    previous_failure: FailureType | None,
) -> LegView | None:
    """Pick the next unused leg that still accepts this request.

    payload failures never reach here: the task is already terminal.
    """
    if previous_failure is FailureType.PAYLOAD:
        return None

    for leg in sorted(legs, key=lambda item: item.priority):
        if leg.id in used_leg_ids:
            continue
        if ref_image_count > leg.max_ref_images:
            continue
        if (
            previous_failure is FailureType.MODERATION
            and leg.skip_on_moderation
        ):
            continue
        return leg
    return None
