import os
from pathlib import Path
import pytest


DEST_DIR = Path("/usr/local/bin")

def _scripts():
    scripts_dir = Path(os.environ["SCRIPTS_SRC_DIR"])
    return sorted(p.name for p in scripts_dir.iterdir() if p.is_file() and not p.name.startswith("."))

@pytest.fixture(params=_scripts(), ids=str)
def deployed_script_name(request):
    return request.param


def test_scripts_are_present(host, deployed_script_name):
    f = host.file(str(DEST_DIR / deployed_script_name))   
    assert f.exists
    assert f.is_file
    assert f.user == "root"
    assert f.group == "root"


def test_no_j2_files_copied(host):
    bin_dir = host.file("/usr/local/bin")

    j2_files = [
        f for f in bin_dir.listdir()
        if f.endswith(".j2")
    ]

    assert j2_files == [], f"Unexpected .j2 files found: {j2_files}"


def test_backup_restore_conf_file(host):
    f = host.file("/etc/backup-restore.conf")
    assert f.exists
    assert f.is_file
    assert f.user == "root"
    assert f.group == "root"
    assert f.mode & 0o777 == 0o644


def test_remote_shell_default_is_set_once(host):
    f = host.file("/etc/backup-restore.conf")
    content = f.content_string

    lines = [l for l in content.splitlines() if l.startswith("remote_shell=")]
    assert len(lines) == 1
    assert lines[0] == 'remote_shell="ssh"'
