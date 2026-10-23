from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    user_id: UUID
    model_slug: str
    prompt: str
    ref_images: list[str] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    task_id: UUID


class PaymentWebhook(BaseModel):
    payment_id: str
    user_id: UUID
    tokens: int
    status: str


class ProviderWebhook(BaseModel):
    external_id: str
    status: str
    file_url: str | None = None
    error_type: str | None = None


class AttemptOut(BaseModel):
    provider: str
    status: str
    error_type: str | None
    external_id: str | None
    started_at: datetime
    finished_at: datetime | None


class CurrentLegOut(BaseModel):
    provider: str
    priority: int


class TaskOut(BaseModel):
    id: UUID
    status: str
    current_leg: CurrentLegOut | None
    result_url: str | None
    error_type: str | None
    attempts: list[AttemptOut]


class JournalRowOut(BaseModel):
    amount: int
    kind: str
    reference_id: str
    created_at: datetime


class BalanceOut(BaseModel):
    user_id: UUID
    balance: int
    journal: list[JournalRowOut]
