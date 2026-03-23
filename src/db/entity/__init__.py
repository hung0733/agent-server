"""
Entity layer - SQLAlchemy ORM models mapped to database tables.

This layer contains the canonical entity definitions that map directly
to database tables. Each entity corresponds to one table in the schema.

Example:
    from db.entity.user_entity import User, APIKey

    # Or to import from the module:
    from db.entity import User, APIKey

    # Entities are used with SQLAlchemy ORM operations
    session.query(User).filter_by(id=1).first()
"""

# Note: For individual imports, it's recommended to import from specific modules
# like: from db.entity.user_entity import User, APIKey
# rather than relying on wildcard imports from the __init__.py

__all__ = [
    # Individual entity modules would be listed here if they were added,
    # but due to circular import considerations, specific module imports
    # are preferred over wildcard imports. 
]