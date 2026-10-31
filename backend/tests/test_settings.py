from pathlib import Path

import app.settings
from app.settings import Settings


def test_env_file_is_pinned_to_backend_dir() -> None:
    expected = Path(app.settings.__file__).resolve().parent.parent / ".env"
    assert Settings.model_config["env_file"] == expected
