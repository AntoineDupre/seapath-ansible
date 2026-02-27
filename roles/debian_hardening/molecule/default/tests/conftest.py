import pytest

HARDENED_SERVICES = ["syslog-ng"]

KERNEL_PARAMS = [
    "init_on_alloc=1",
    "init_on_free=1",
    "slab_nomerge",
    "pti=on",
    "slub_debug=ZF",
    "randomize_kstack_offset=on",
    "slab_common.usercopy_fallback=N",
    "iommu=pt",
    "security=yama",
    "mce=0",
    "rng_core.default_quality=500",
    "lsm=apparmor,lockdown,capability,landlock,yama,bpf,integrity",
]

SYSCTL_FILES = [
    "/etc/sysctl.d/50-coredump.conf",
    "/etc/sysctl.d/50-kexec.conf",
    "/etc/sysctl.d/50-binfmt_misc.conf",
    "/etc/sysctl.d/zz-sysctl-hardening.conf",
    "/etc/sysctl.d/99-sysctl-network.conf",
]

PROFILE_SCRIPTS = [
    "/etc/profile.d/mktmpdir.sh",
    "/etc/profile.d/terminal_idle.sh",
]


@pytest.fixture(params=HARDENED_SERVICES)
def hardened_service(request):
    """Fixture that yields each hardened service name, one at a time."""
    return request.param


@pytest.fixture(params=SYSCTL_FILES)
def sysctl_file(request):
    """Fixture that yields each expected sysctl config file path."""
    return request.param
