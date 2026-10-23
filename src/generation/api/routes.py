from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from generation.api.deps import get_workflow
from generation.api.schemas import (
    AttemptOut,
    BalanceOut,
    CurrentLegOut,
    GenerateRequest,
    GenerateResponse,
    JournalRowOut,
    PaymentWebhook,
    ProviderWebhook,
    TaskOut,
)
from generation.application.workflow import Workflow
from generation.config import settings
from generation.domain.exceptions import (
    ActiveTaskLimitError,
    InsufficientTokensError,
    InvalidSignatureError,
    NoSuitableLegError,
    UnknownModelError,
)
from generation.infrastructure.security import verify_signature

router = APIRouter()
WorkflowDep = Annotated[Workflow, Depends(get_workflow)]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/generate", response_model=GenerateResponse)
async def generate(payload: GenerateRequest, workflow: WorkflowDep) -> GenerateResponse:
    try:
        task_id = await workflow.generate(
            user_id=payload.user_id,
            model_slug=payload.model_slug,
            prompt=payload.prompt,
            ref_images=payload.ref_images,
        )
    except UnknownModelError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except NoSuitableLegError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except InsufficientTokensError as exc:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(exc)) from exc
    except ActiveTaskLimitError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    return GenerateResponse(task_id=task_id)


@router.post("/webhooks/payments", status_code=status.HTTP_202_ACCEPTED)
async def payment_webhook(request: Request, workflow: WorkflowDep) -> dict[str, str]:
    body = await request.body()
    _verify(request, body)
    payload = PaymentWebhook.model_validate_json(body)
    await workflow.handle_payment(
        payment_id=payload.payment_id,
        user_id=payload.user_id,
        tokens=payload.tokens,
        status=payload.status,
    )
    return {"status": "accepted"}


@router.post(
    "/webhooks/providers/{name}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def provider_webhook(
    name: str,
    request: Request,
    workflow: WorkflowDep,
) -> dict[str, str]:
    body = await request.body()
    _verify(request, body)
    payload = ProviderWebhook.model_validate_json(body)
    await workflow.handle_provider_webhook(
        provider=name,
        external_id=payload.external_id,
        status=payload.status,
        file_url=payload.file_url,
        error_type=payload.error_type,
    )
    return {"status": "accepted"}


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: UUID, workflow: WorkflowDep) -> TaskOut:
    task = await workflow.get_task(task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    current = None
    if task.current_leg is not None:
        current = CurrentLegOut(
            provider=task.current_leg.provider,
            priority=task.current_leg.priority,
        )
    return TaskOut(
        id=task.id,
        status=task.status,
        current_leg=current,
        result_url=task.result_url,
        error_type=task.error_type,
        attempts=[
            AttemptOut(
                provider=item.provider,
                status=item.status,
                error_type=item.error_type,
                external_id=item.external_id,
                started_at=item.started_at,
                finished_at=item.finished_at,
            )
            for item in task.attempts
        ],
    )


@router.get("/users/{user_id}/balance", response_model=BalanceOut)
async def get_balance(user_id: UUID, workflow: WorkflowDep) -> BalanceOut:
    result = await workflow.get_balance(user_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    balance, rows = result
    return BalanceOut(
        user_id=user_id,
        balance=balance,
        journal=[
            JournalRowOut(
                amount=row.amount,
                kind=row.kind,
                reference_id=row.reference_id,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


def _verify(request: Request, body: bytes) -> None:
    try:
        verify_signature(
            settings.webhook_secret,
            body,
            request.headers.get("X-Signature"),
        )
    except InvalidSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
