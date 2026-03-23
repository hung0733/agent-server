"""SQLAlchemy declarative base for new entity layer.

This base class is separate from the legacy db.base.Base to avoid
registry conflicts during the migration period. Once migration is complete,
this can be merged back with the legacy base.
"""

from sqlalchemy.orm import DeclarativeBase


class EntityBase(DeclarativeBase):
    """Base class for all new SQLAlchemy declarative entity models.
    
    This base class provides a separate registry from the legacy Base
    to avoid 'Multiple classes found for path' errors when both old
    schema and new entities define classes with the same names.
    
    Once the migration from schema/ to entity/ is complete, all entities
    can be updated to use the unified db.base.Base.
    
    Example:
        class User(EntityBase):
            __tablename__ = "users"
            
            id = Column(Integer, primary_key=True)
            name = Column(String)
    """
    
    pass