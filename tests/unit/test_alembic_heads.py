from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


class TestAlembicHeads:
    def test_has_single_migration_head(self):
        config = Config("alembic.ini")
        script = ScriptDirectory.from_config(config)

        assert script.get_heads() == [script.get_current_head()]
