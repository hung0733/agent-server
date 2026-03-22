"""SQLAlchemy declarative base for database models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models.
    
    This base class provides common configuration for all models
    in the application, including metadata and naming conventions.
    
    Example:
        class User(Base):
            __tablename__ = "users"
            
            id = Column(Integer, primary_key=True)
            name = Column(String)
    """
    
    pass
