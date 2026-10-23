from enum import StrEnum


class TaskStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AttemptStatus(StrEnum):
    SENT = "sent"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class FailureType(StrEnum):
    TECHNICAL = "technical"
    MODERATION = "moderation"
    PAYLOAD = "payload"


class LedgerKind(StrEnum):
    PAYMENT = "payment"
    DEBIT = "debit"
    REFUND = "refund"
