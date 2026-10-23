from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from generation.domain.enums import LedgerKind
from generation.infrastructure.db.models import LedgerEntry


async def add_ledger_entry(
    session: AsyncSession,
    *,
    user_id: UUID,
    amount: int,
    kind: LedgerKind,
    reference_id: str,
) -> bool:
    """Insert a money movement. Returns False if this movement already exists.

    Uniqueness on (kind, reference_id) is the exactly-once guarantee.
    Concurrent workers racing on the same payment or refund hit
    ON CONFLICT DO NOTHING; only one row is written, the session stays open.
    """
    statement = (
        insert(LedgerEntry)
        .values(
            id=uuid4(),
            user_id=user_id,
            amount=amount,
            kind=kind.value,
            reference_id=reference_id,
        )
        .on_conflict_do_nothing(constraint="uq_ledger_kind_reference")
        .returning(LedgerEntry.id)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none() is not None
