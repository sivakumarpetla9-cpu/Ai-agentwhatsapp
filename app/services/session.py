from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, EntityNotFoundError
from app.core.logging import get_logger
from app.models.customer import CustomerSession
from app.models.restaurant import RestaurantTable
from app.repositories.customer import CustomerRepository, CustomerSessionRepository
from app.repositories.restaurant import RestaurantRepository, RestaurantTableRepository
from app.schemas.session import (
    CustomerSessionResponse,
    DirectTablesResponse,
    QREntryResponse,
    SimpleRestaurantResponse,
    SimpleTableResponse,
)
from app.services.base import BaseService

logger = get_logger("app.services.session")


def mask_identifier(identity: str) -> str:
    """
    Mask sensitive customer identifiers for privacy-safe logging.
    e.g. "+919876543210" -> "+9******10"
    """
    if not identity:
        return "UNKNOWN"
    if len(identity) <= 4:
        return "****"
    return f"{identity[:2]}******{identity[-2:]}"


class SessionService(BaseService):
    """
    Service handling Table Identification and Customer Session lifecycle.
    """
    DEFAULT_SESSION_DURATION_HOURS = 8

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.restaurant_repo = RestaurantRepository(session)
        self.table_repo = RestaurantTableRepository(session)
        self.customer_repo = CustomerRepository(session)
        self.session_repo = CustomerSessionRepository(session)

    async def resolve_qr(self, qr_token: str) -> QREntryResponse:
        """
        Validate table QR token and resolve public restaurant and table context.
        """
        table = await self.table_repo.get_by_qr_token(qr_token)
        if not table:
            logger.warning("QR resolution failed: Token not found.")
            raise EntityNotFoundError(
                message="Invalid or expired QR code token.",
                error_code="QR_TOKEN_NOT_FOUND",
            )

        if not table.restaurant.is_active:
            logger.warning(f"QR resolution rejected: Restaurant '{table.restaurant_id}' is inactive.")
            raise BadRequestError(
                message="This restaurant is currently closed or inactive.",
                error_code="RESTAURANT_INACTIVE",
            )

        if not table.is_active:
            logger.warning(f"QR resolution rejected: Table '{table.id}' is inactive.")
            raise BadRequestError(
                message="This table is currently unavailable.",
                error_code="TABLE_INACTIVE",
            )

        return QREntryResponse(
            restaurant=SimpleRestaurantResponse(
                id=table.restaurant.id,
                name=table.restaurant.name,
            ),
            table=SimpleTableResponse(
                id=table.id,
                table_number=table.table_number,
            ),
        )

    async def list_active_tables_for_direct_entry(
        self, restaurant_id: UUID
    ) -> DirectTablesResponse:
        """
        Retrieve available active dining tables for customer selection in direct WhatsApp flow.
        """
        restaurant = await self.restaurant_repo.get_by_id(restaurant_id)
        if not restaurant or not restaurant.is_active:
            raise EntityNotFoundError(
                message=f"Restaurant '{restaurant_id}' not found or inactive.",
                error_code="RESTAURANT_NOT_FOUND",
            )

        all_tables = await self.table_repo.list_by_restaurant(restaurant_id)
        active_tables = [t for t in all_tables if t.is_active]

        return DirectTablesResponse(
            tables=[
                SimpleTableResponse(id=t.id, table_number=t.table_number)
                for t in active_tables
            ]
        )

    async def create_or_resume_direct_session(
        self,
        customer_session_identity: str,
        restaurant_id: UUID,
        table_id: UUID,
    ) -> CustomerSessionResponse:
        """
        Create a new session or resume an active session for direct table selection.
        Enforces cross-restaurant isolation, active flags, and privacy protection.
        """
        masked_id = mask_identifier(customer_session_identity)
        logger.info(
            f"Session request for customer={masked_id}, "
            f"restaurant={restaurant_id}, table={table_id}"
        )

        # 1. Validate restaurant
        restaurant = await self.restaurant_repo.get_by_id(restaurant_id)
        if not restaurant or not restaurant.is_active:
            raise BadRequestError(
                message="Target restaurant is invalid or inactive.",
                error_code="RESTAURANT_INACTIVE",
            )

        # 2. Validate table belongs to this restaurant
        table = await self.table_repo.get_by_id_and_restaurant(
            id=table_id, restaurant_id=restaurant_id
        )
        if not table:
            logger.warning(
                f"Session creation rejected: Table '{table_id}' does not belong "
                f"to Restaurant '{restaurant_id}'."
            )
            raise BadRequestError(
                message="Selected table does not belong to this restaurant.",
                error_code="CROSS_RESTAURANT_TABLE_REJECTED",
            )

        if not table.is_active:
            raise BadRequestError(
                message="Selected table is currently unavailable.",
                error_code="TABLE_INACTIVE",
            )

        # 3. Resolve or create customer (without logging raw phone/ID)
        customer = await self.customer_repo.get_or_create(customer_session_identity)

        # 4. Check for existing active session
        existing_session = await self.session_repo.get_active_session_for_customer(customer.id)
        if existing_session:
            if (
                existing_session.restaurant_id == restaurant_id
                and existing_session.table_id == table_id
            ):
                logger.info(f"Reusing existing active session '{existing_session.id}' for customer={masked_id}.")
                return CustomerSessionResponse(
                    session_id=existing_session.id,
                    restaurant_id=existing_session.restaurant_id,
                    table_id=existing_session.table_id,
                    status=existing_session.status,
                )
            else:
                # Customer switched table or restaurant -> retire previous session
                logger.info(
                    f"Customer {masked_id} switched table/restaurant. Expiring old session '{existing_session.id}'."
                )
                await self.session_repo.expire_active_sessions_for_customer(customer.id)

        # 5. Create new active session
        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=self.DEFAULT_SESSION_DURATION_HOURS
        )
        new_session = CustomerSession(
            customer_id=customer.id,
            restaurant_id=restaurant_id,
            table_id=table_id,
            status="ACTIVE",
            expires_at=expires_at,
        )
        await self.session_repo.create(new_session)
        logger.info(f"Created new active session '{new_session.id}' for customer={masked_id}.")

        return CustomerSessionResponse(
            session_id=new_session.id,
            restaurant_id=new_session.restaurant_id,
            table_id=new_session.table_id,
            status=new_session.status,
        )

    async def create_or_resume_qr_session(
        self,
        customer_session_identity: str,
        qr_token: str,
    ) -> CustomerSessionResponse:
        """
        Validate table QR token and create or resume an active dining session.
        """
        table = await self.table_repo.get_by_qr_token(qr_token)
        if not table:
            raise EntityNotFoundError(
                message="Invalid or expired QR code token.",
                error_code="QR_TOKEN_NOT_FOUND",
            )

        return await self.create_or_resume_direct_session(
            customer_session_identity=customer_session_identity,
            restaurant_id=table.restaurant_id,
            table_id=table.id,
        )
