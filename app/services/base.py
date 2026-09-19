from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logging import get_logger


class BaseService:
    """
    Base service layer class handling business workflows and transactions.
    """
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger(self.__class__.__name__)
