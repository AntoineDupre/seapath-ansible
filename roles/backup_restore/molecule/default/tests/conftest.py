import os
from pathlib import Path
import pytest


def _scripts():
    scripts_dir = Path(os.environ["SCRIPTS_SRC_DIR"])
    return sorted(
        p.name
        for p in scripts_dir.iterdir()
        if p.is_file() and not p.name.startswith(".")
    )


@pytest.fixture(params=_scripts(), ids=str)
def deployed_script_name(request):
    return request.param
