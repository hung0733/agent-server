from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.base import Base


ModelT = TypeVar("ModelT", bound=Base)


class BaseDAO(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id_: int) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def list(self, *, offset: int = 0, limit: int = 100) -> list[ModelT]:
        stmt = select(self.model).offset(offset).limit(limit)
        result = await self.session.scalars(stmt)
        return list(result)

    async def create(self, data: BaseModel | dict[str, Any]) -> ModelT:
        values = self._to_dict(data)
        item = self.model(**values)
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def update(self, item: ModelT, data: BaseModel | dict[str, Any]) -> ModelT:
        values = self._to_dict(data, exclude_unset=True)
        for key, value in values.items():
            setattr(item, key, value)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def delete(self, item: ModelT) -> None:
        await self.session.delete(item)
        await self.session.flush()

    def _to_dict(self, data: BaseModel | dict[str, Any], *, exclude_unset: bool = False) -> dict[str, Any]:
        if isinstance(data, BaseModel):
            return data.model_dump(exclude_unset=exclude_unset)
        return data
