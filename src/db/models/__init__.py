"""
Database models package.

This package provides Pydantic base models for database entities.
"""
from db.models.base import BaseModelWithID, now_utc

__all__ = ["BaseModelWithID", "now_utc"]
