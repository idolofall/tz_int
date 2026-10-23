from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from generation.application.ledger import add_ledger_entry
from generation.config import Settings
from generation.domain.enums import AttemptStatus, FailureType, LedgerKind, TaskStatus
from generation.domain.exceptions import (
    ActiveTaskLimitError,
    InsufficientTokensError,
    NoSuitableLegError,
    UnknownModelError,
)
from generation.domain.rules import LegView, choose_next_leg
from generation.infrastructure.db.models import (
    GenerationTask,
    LedgerEntry,
    Model,
    ModelLeg,
    TaskAttempt,
    User,
)
from generation.infrastructure.providers import ProviderClient

logger = logging.getLogger(__name__)


class Workflow:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        provider_client: ProviderClient,
    ) -> None:
        self._sessions = session_factory
        self._settings = settings
        self._providers = provider_client

    async def generate(
        self,
        *,
        user_id: UUID,
        model_slug: str,
        prompt: str,
        ref_images: list[str],
    ) -> UUID:
        async with self._sessions() as session, session.begin():
            await self._ensure_user(session, user_id)
            user = await session.get(User, user_id, with_for_update=True)
            assert user is not None

            model = await session.get(
                Model, model_slug, options=(selectinload(Model.legs),)
            )
            if model is None:
                raise UnknownModelError(model_slug)

            first_leg = choose_next_leg(
                _leg_views(model.legs),
                ref_image_count=len(ref_images),
                used_leg_ids=set(),
                previous_failure=None,
            )
            if first_leg is None:
                raise NoSuitableLegError(
                    "no provider leg accepts this many reference images"
                )

            active = await session.scalar(
                select(func.count())
                .select_from(GenerationTask)
                .where(
                    GenerationTask.user_id == user_id,
                    GenerationTask.status == TaskStatus.PROCESSING,
                )
            )
            if (active or 0) >= self._settings.max_active_tasks:
                raise ActiveTaskLimitError("active task limit reached")

            balance = await session.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                    LedgerEntry.user_id == user_id
                )
            )
            if (balance or 0) < model.price_tokens:
                raise InsufficientTokensError("not enough tokens")

            task = GenerationTask(
                id=uuid4(),
                user_id=user_id,
                model_slug=model.slug,
                prompt=prompt,
                ref_images=ref_images,
                status=TaskStatus.PROCESSING,
                current_leg_id=first_leg.id,
            )
            session.add(task)
            await session.flush()

            await add_ledger_entry(
                session,
                user_id=user_id,
                amount=-model.price_tokens,
                kind=LedgerKind.DEBIT,
                reference_id=str(task.id),
            )
            attempt = self._new_attempt(task, first_leg)
            session.add(attempt)

        await self._dispatch(task.id, attempt.id)
        return task.id

    async def handle_payment(
        self,
        *,
        payment_id: str,
        user_id: UUID,
        tokens: int,
        status: str,
    ) -> None:
        if status not in {"completed", "success", "paid"}:
            return
        if tokens <= 0:
            return

        async with self._sessions() as session, session.begin():
            await self._ensure_user(session, user_id)
            await add_ledger_entry(
                session,
                user_id=user_id,
                amount=tokens,
                kind=LedgerKind.PAYMENT,
                reference_id=payment_id,
            )

    async def handle_provider_webhook(
        self,
        *,
        provider: str,
        external_id: str,
        status: str,
        file_url: str | None,
        error_type: str | None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            attempt = await session.scalar(
                select(TaskAttempt)
                .options(
                    selectinload(TaskAttempt.task).selectinload(GenerationTask.attempts),
                    selectinload(TaskAttempt.task)
                    .selectinload(GenerationTask.current_leg),
                )
                .where(
                    TaskAttempt.provider == provider,
                    TaskAttempt.external_id == external_id,
                )
            )
            if attempt is None:
                logger.info(
                    "ignored webhook for unknown attempt %s/%s", provider, external_id
                )
                return

            task = attempt.task
            if status == "completed":
                won = await self._finalize_attempt(
                    session,
                    attempt,
                    AttemptStatus.COMPLETED,
                    error_type=None,
                )
                if not won:
                    # Late or duplicate completed: do not attach a result
                    # after the attempt already left SENT (rule 6).
                    logger.info(
                        "ignored late/duplicate completed for attempt %s", attempt.id
                    )
                    return
                if task.status != TaskStatus.PROCESSING:
                    return
                task.status = TaskStatus.COMPLETED
                task.result_url = file_url
                task.error_type = None
                return

            failure = _parse_failure(error_type)
            won = await self._finalize_attempt(
                session,
                attempt,
                AttemptStatus.FAILED,
                error_type=failure.value,
            )
            if not won:
                return
            next_attempt_id = await self._advance_after_failure(session, task, failure)

        if next_attempt_id is not None:
            await self._dispatch(task.id, next_attempt_id)

    async def watchdog_tick(self) -> int:
        now = datetime.now(UTC)
        handled = 0
        async with self._sessions() as session, session.begin():
            expired = (
                await session.scalars(
                    select(TaskAttempt)
                    .options(
                        selectinload(TaskAttempt.task).selectinload(
                            GenerationTask.attempts
                        )
                    )
                    .where(
                        TaskAttempt.status == AttemptStatus.SENT,
                        TaskAttempt.timeout_at <= now,
                    )
                    .order_by(TaskAttempt.timeout_at)
                    .limit(25)
                    .with_for_update(skip_locked=True)
                )
            ).all()

            dispatch_queue: list[tuple[UUID, UUID]] = []
            for attempt in expired:
                won = await self._finalize_attempt(
                    session,
                    attempt,
                    AttemptStatus.TIMED_OUT,
                    error_type=FailureType.TECHNICAL.value,
                )
                if not won:
                    continue
                next_id = await self._advance_after_failure(
                    session, attempt.task, FailureType.TECHNICAL
                )
                if next_id is not None:
                    dispatch_queue.append((attempt.task_id, next_id))
                handled += 1

        for task_id, attempt_id in dispatch_queue:
            await self._dispatch(task_id, attempt_id)
        return handled

    async def get_task(self, task_id: UUID) -> GenerationTask | None:
        async with self._sessions() as session:
            return await session.get(
                GenerationTask,
                task_id,
                options=(
                    selectinload(GenerationTask.current_leg),
                    selectinload(GenerationTask.attempts),
                ),
            )

    async def get_balance(self, user_id: UUID) -> tuple[int, list[LedgerEntry]] | None:
        async with self._sessions() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            balance = await session.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                    LedgerEntry.user_id == user_id
                )
            )
            rows = (
                await session.scalars(
                    select(LedgerEntry)
                    .where(LedgerEntry.user_id == user_id)
                    .order_by(LedgerEntry.created_at.desc())
                    .limit(20)
                )
            ).all()
            return int(balance or 0), list(rows)

    async def _dispatch(self, task_id: UUID, attempt_id: UUID) -> None:
        async with self._sessions() as session:
            attempt = await session.get(
                TaskAttempt,
                attempt_id,
                options=(
                    selectinload(TaskAttempt.task),
                    selectinload(TaskAttempt.leg),
                ),
            )
            if attempt is None or attempt.status != AttemptStatus.SENT:
                return
            task = attempt.task
            if attempt.external_id is None:
                attempt.external_id = str(uuid4())
                await session.commit()
            external_id = attempt.external_id
            provider = attempt.provider
            payload = {
                "prompt": task.prompt,
                "ref_images": task.ref_images,
                "model": task.model_slug,
                "external_id": external_id,
                "webhook_url": (
                    f"{self._settings.app_public_url.rstrip('/')}"
                    f"/webhooks/providers/{provider}"
                ),
            }

        try:
            await self._providers.create_task(
                base_url=self._settings.provider_base_url(provider),
                payload=payload,
            )
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("sync dispatch failed for attempt %s: %s", attempt_id, exc)
            async with self._sessions() as session, session.begin():
                attempt = await session.get(
                    TaskAttempt,
                    attempt_id,
                    options=(
                        selectinload(TaskAttempt.task).selectinload(
                            GenerationTask.attempts
                        ),
                    ),
                )
                if attempt is None:
                    return
                won = await self._finalize_attempt(
                    session,
                    attempt,
                    AttemptStatus.FAILED,
                    error_type=FailureType.TECHNICAL.value,
                )
                next_id = None
                if won:
                    next_id = await self._advance_after_failure(
                        session, attempt.task, FailureType.TECHNICAL
                    )
            if next_id is not None:
                await self._dispatch(task_id, next_id)
            return

    async def _advance_after_failure(
        self,
        session: AsyncSession,
        task: GenerationTask,
        failure: FailureType,
    ) -> UUID | None:
        if task.status != TaskStatus.PROCESSING:
            return None

        if failure is FailureType.PAYLOAD:
            await self._fail_and_refund(session, task, failure)
            return None

        model = await session.get(
            Model, task.model_slug, options=(selectinload(Model.legs),)
        )
        assert model is not None
        used = {item.leg_id for item in task.attempts}
        nxt = choose_next_leg(
            _leg_views(model.legs),
            ref_image_count=len(task.ref_images),
            used_leg_ids=used,
            previous_failure=failure,
        )
        if nxt is None:
            await self._fail_and_refund(session, task, failure)
            return None

        attempt = self._new_attempt(task, nxt)
        session.add(attempt)
        task.current_leg_id = nxt.id
        await session.flush()
        return attempt.id

    async def _fail_and_refund(
        self,
        session: AsyncSession,
        task: GenerationTask,
        failure: FailureType,
    ) -> None:
        debit = await session.scalar(
            select(LedgerEntry.amount).where(
                LedgerEntry.kind == LedgerKind.DEBIT.value,
                LedgerEntry.reference_id == str(task.id),
            )
        )
        refund_amount = abs(int(debit or 0))
        if refund_amount:
            await add_ledger_entry(
                session,
                user_id=task.user_id,
                amount=refund_amount,
                kind=LedgerKind.REFUND,
                reference_id=str(task.id),
            )
        task.status = TaskStatus.FAILED
        task.error_type = failure.value
        task.result_url = None

    async def _finalize_attempt(
        self,
        session: AsyncSession,
        attempt: TaskAttempt,
        status: AttemptStatus,
        *,
        error_type: str | None,
    ) -> bool:
        result = await session.execute(
            update(TaskAttempt)
            .where(
                TaskAttempt.id == attempt.id,
                TaskAttempt.status == AttemptStatus.SENT,
            )
            .values(
                status=status.value,
                error_type=error_type,
                finished_at=datetime.now(UTC),
            )
        )
        if result.rowcount != 1:
            return False
        attempt.status = status.value
        attempt.error_type = error_type
        attempt.finished_at = datetime.now(UTC)
        return True

    def _new_attempt(
        self, task: GenerationTask, leg: LegView | ModelLeg
    ) -> TaskAttempt:
        now = datetime.now(UTC)
        return TaskAttempt(
            task_id=task.id,
            leg_id=leg.id,
            provider=leg.provider,
            status=AttemptStatus.SENT,
            timeout_at=now + timedelta(seconds=self._settings.provider_timeout_seconds),
        )

    async def _ensure_user(self, session: AsyncSession, user_id: UUID) -> None:
        await session.execute(insert(User).values(id=user_id).on_conflict_do_nothing())


def _leg_views(legs: list[ModelLeg]) -> list[LegView]:
    return [
        LegView(
            id=leg.id,
            provider=leg.provider,
            priority=leg.priority,
            max_ref_images=leg.max_ref_images,
            skip_on_moderation=leg.skip_on_moderation,
        )
        for leg in legs
    ]


def _parse_failure(error_type: str | None) -> FailureType:
    try:
        return FailureType(error_type)
    except ValueError:
        return FailureType.TECHNICAL
