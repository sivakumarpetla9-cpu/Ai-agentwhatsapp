from typing import Any, Generic, List, Optional, Type, TypeVar
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic base repository encapsulating common database interactions.
    """
    def __init__(self, model: Type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get_by_id(self, id: Any) -> Optional[ModelType]:
        """
        Fetch a single entity by primary key.
        """
        return await self.session.get(self.model, id)

    async def list_all(self, skip: int = 0, limit: int = 100) -> List[ModelType]:
        """
        List entities with pagination.
        """
        statement = select(self.model).offset(skip).limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def create(self, entity: ModelType) -> ModelType:
        """
        Persist a new entity to the database.
        """
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: ModelType) -> None:
        """
        Delete an existing entity.
        """
        await self.session.delete(entity)
        await self.session.flush()


class BaseRestaurantRepository(BaseRepository[ModelType]):
    """
    Base repository enforcing multi-tenant isolation by restaurant_id.
    All restaurant-scoped resources must query through this repository layer.
    """
    async def get_by_id_and_restaurant(
        self, id: Any, restaurant_id: UUID
    ) -> Optional[ModelType]:
        """
        Retrieve an entity belonging strictly to a given restaurant.
        """
        statement = (
            select(self.model)
            .where(
                getattr(self.model, "id") == id,
                getattr(self.model, "restaurant_id") == restaurant_id,
            )
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def list_by_restaurant(
        self, restaurant_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[ModelType]:
        """
        List all entities belonging strictly to a given restaurant.
        """
        statement = (
            select(self.model)
            .where(getattr(self.model, "restaurant_id") == restaurant_id)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
