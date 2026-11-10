from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base


def test_alembic_script_and_metadata():
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / 'src/infrastructure/alembic/alembic.ini'))
    script = ScriptDirectory.from_config(cfg)
    assert Path(script.dir).is_dir()
    assert Path(script.dir, 'env.py').is_file()
    assert Path(script.dir, 'versions').is_dir()
    load_models()
    assert Base.metadata is not None
    assert list(script.walk_revisions()) == []
