import pytest

from conftest import KERNEL_PARAMS, PROFILE_SCRIPTS


# ---------------------------------------------------------------------------
# Groups — @pytest.mark.parametrize
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("group", ["ansible", "privileged"])
def test_groups_exist(host, group):
    assert host.group(group).exists


# ---------------------------------------------------------------------------
# Kernel parameters in grub — @pytest.mark.parametrize over 13 params
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("param", KERNEL_PARAMS)
def test_kernel_param_in_grub(host, param):
    grub = host.file("/etc/default/grub")
    assert grub.exists
    assert param in grub.content_string


# ---------------------------------------------------------------------------
# Sysctl config files — @pytest.fixture(params=...) from conftest
# ---------------------------------------------------------------------------
def test_sysctl_config_exists(host, sysctl_file):
    f = host.file(sysctl_file)
    assert f.exists
    assert f.is_file


# ---------------------------------------------------------------------------
# Profile scripts — @pytest.mark.parametrize
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("script", PROFILE_SCRIPTS)
def test_profile_script_deployed(host, script):
    f = host.file(script)
    assert f.exists
    assert f.is_file


# ---------------------------------------------------------------------------
# Systemd service hardening — @pytest.fixture(params=...) from conftest
# ---------------------------------------------------------------------------
def test_service_hardening_directory(host, hardened_service):
    d = host.file(
        f"/etc/systemd/system/{hardened_service}.service.d"
    )
    assert d.exists
    assert d.is_directory
    assert d.user == "root"
    assert d.group == "root"


def test_service_hardening_conf(host, hardened_service):
    f = host.file(
        f"/etc/systemd/system/{hardened_service}.service.d/hardening.conf"
    )
    assert f.exists
    assert f.is_file


# ---------------------------------------------------------------------------
# SSH hardening
# ---------------------------------------------------------------------------
def test_ssh_hardening_config(host):
    f = host.file("/etc/ssh/sshd_config.d/ssh-audit_hardening.conf")
    assert f.exists
    assert f.is_file


# ---------------------------------------------------------------------------
# Sudoers
# ---------------------------------------------------------------------------
def test_sudoers_security_file(host):
    f = host.file("/etc/sudoers.d/00-security")
    assert f.exists
    assert f.user == "root"
    assert f.group == "root"
    assert f.mode == 0o440


def test_sudo_binary_permissions(host):
    f = host.file("/usr/bin/sudo")
    assert f.exists
    assert f.group == "privileged"
    assert f.mode == 0o4750


# ---------------------------------------------------------------------------
# PAM su — @pytest.mark.parametrize
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pam_file", ["/etc/pam.d/su", "/etc/pam.d/su-l"])
def test_pam_su_hardened(host, pam_file):
    f = host.file(pam_file)
    assert f.exists
    assert "pam_wheel.so" in f.content_string


# ---------------------------------------------------------------------------
# Securetty
# ---------------------------------------------------------------------------
def test_securetty_exists(host):
    f = host.file("/etc/securetty")
    assert f.exists
    assert f.user == "root"
    assert f.mode == 0o644


# ---------------------------------------------------------------------------
# login.defs
# ---------------------------------------------------------------------------
def test_login_defs_pass_max_days(host):
    f = host.file("/etc/login.defs")
    assert f.exists
    assert "PASS_MAX_DAYS 90" in f.content_string


# ---------------------------------------------------------------------------
# Grub password
# ---------------------------------------------------------------------------
def test_grub_password_file(host):
    f = host.file("/etc/grub.d/01_password")
    assert f.exists
    assert f.mode == 0o755
    assert "DEADBEEF" in f.content_string


def test_grub_unrestricted_class(host):
    f = host.file("/etc/grub.d/10_linux")
    assert f.exists
    assert "--unrestricted" in f.content_string


# ---------------------------------------------------------------------------
# Audit configuration — @pytest.mark.parametrize
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "audit_file",
    [
        "/etc/audit/plugins.d/syslog.conf",
        "/etc/audit/rules.d/audit.rules",
    ],
)
def test_audit_config_deployed(host, audit_file):
    f = host.file(audit_file)
    assert f.exists
    assert f.is_file


# ---------------------------------------------------------------------------
# random-root-passwd service
# ---------------------------------------------------------------------------
def test_random_root_passwd_service(host):
    f = host.file("/etc/systemd/system/random-root-passwd.service")
    assert f.exists
    assert f.is_file
