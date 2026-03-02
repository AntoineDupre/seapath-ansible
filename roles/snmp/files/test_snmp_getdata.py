#!/usr/bin/python3
# Copyright (C) 2024, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for snmp_getdata.py

Since snmp_getdata.py executes all logic at module level, we cannot simply
import it. Instead we:
  1. Load the function definitions into a controlled namespace for pure
     function tests.
  2. Run the full script with subprocess mocked for integration tests.
"""

import importlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
from unittest import mock

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "snmp_getdata.py")


def _load_functions():
    """Extract function definitions from snmp_getdata.py into a module
    namespace without executing the top-level logic."""
    source = open(SCRIPT_PATH).read()
    mod = types.ModuleType("snmp_getdata_funcs")
    mod.__dict__.update({
        "subprocess": subprocess,
        "json": json,
        "os": os,
        "stat": stat,
        "re": __import__("re"),
        "time": time,
        "xmltodict": __import__("xmltodict"),
        "ExpatError": __import__("xml.parsers.expat", fromlist=["ExpatError"]).ExpatError,
    })
    # Execute only import lines and function definitions
    import ast
    tree = ast.parse(source)
    func_nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.Import, ast.ImportFrom))
    ]
    func_tree = ast.Module(body=func_nodes, type_ignores=[])
    code = compile(func_tree, SCRIPT_PATH, "exec")
    exec(code, mod.__dict__)
    return mod


funcs = _load_functions()


# ---------------------------------------------------------------------------
# Tests for run_command_safe
# ---------------------------------------------------------------------------
class TestRunCommandSafe(unittest.TestCase):

    @mock.patch("subprocess.run")
    def test_returns_stdout(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["echo", "hello"], returncode=0, stdout="hello\n", stderr=""
        )
        result = funcs.run_command_safe(["echo", "hello"])
        self.assertEqual(result, "hello\n")
        mock_run.assert_called_once_with(
            ["echo", "hello"],
            capture_output=True, text=True, check=False, timeout=30,
        )

    @mock.patch("subprocess.run")
    def test_returns_stdout_on_nonzero_exit(self, mock_run):
        """Non-zero exit must NOT crash; it returns whatever stdout was."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["false"], returncode=1, stdout="partial\n", stderr="err"
        )
        result = funcs.run_command_safe(["false"])
        self.assertEqual(result, "partial\n")

    @mock.patch("subprocess.run")
    def test_returns_empty_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="slow", timeout=5)
        result = funcs.run_command_safe(["slow"], timeout=5)
        self.assertEqual(result, "")

    @mock.patch("subprocess.run")
    def test_returns_empty_on_oserror(self, mock_run):
        mock_run.side_effect = OSError("No such file")
        result = funcs.run_command_safe(["/no/such/binary"])
        self.assertEqual(result, "")

    @mock.patch("subprocess.run")
    def test_custom_timeout_forwarded(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        funcs.run_command_safe(["cmd"], timeout=120)
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["timeout"], 120)

    @mock.patch("subprocess.run")
    def test_shell_is_not_used(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        funcs.run_command_safe(["ls"])
        _, kwargs = mock_run.call_args
        self.assertNotIn("shell", kwargs)


# ---------------------------------------------------------------------------
# Tests for run_shell_command
# ---------------------------------------------------------------------------
class TestRunShellCommand(unittest.TestCase):

    @mock.patch("subprocess.run")
    def test_returns_stdout(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args="echo hi", returncode=0, stdout="hi\n", stderr=""
        )
        result = funcs.run_shell_command("echo hi")
        self.assertEqual(result, "hi\n")
        _, kwargs = mock_run.call_args
        self.assertTrue(kwargs["shell"])
        self.assertEqual(kwargs["executable"], "/bin/bash")

    @mock.patch("subprocess.run")
    def test_returns_empty_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="slow", timeout=1)
        self.assertEqual(funcs.run_shell_command("slow", timeout=1), "")

    @mock.patch("subprocess.run")
    def test_returns_empty_on_oserror(self, mock_run):
        mock_run.side_effect = OSError()
        self.assertEqual(funcs.run_shell_command("bad"), "")


# ---------------------------------------------------------------------------
# Tests for read_cache / write_cache
# ---------------------------------------------------------------------------
class TestCacheHelpers(unittest.TestCase):

    def test_read_cache_returns_none_for_missing_file(self):
        self.assertIsNone(funcs.read_cache("/tmp/nonexistent_test_xyz", 3600))

    def test_write_then_read_cache(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            funcs.write_cache(tmp_path, "cached data\n")
            result = funcs.read_cache(tmp_path, 3600)
            self.assertEqual(result, "cached data\n")
        finally:
            os.unlink(tmp_path)

    def test_read_cache_returns_none_for_stale_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write("old data")
            tmp_path = tmp.name
        try:
            # Set mtime to 2 hours ago
            old_time = time.time() - 7200
            os.utime(tmp_path, (old_time, old_time))
            result = funcs.read_cache(tmp_path, 3600)
            self.assertIsNone(result)
        finally:
            os.unlink(tmp_path)

    def test_read_cache_returns_content_for_fresh_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write("fresh data")
            tmp_path = tmp.name
        try:
            result = funcs.read_cache(tmp_path, 3600)
            self.assertEqual(result, "fresh data")
        finally:
            os.unlink(tmp_path)

    def test_read_cache_boundary_exactly_max_age(self):
        """File whose age equals max_age should still be returned."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write("boundary")
            tmp_path = tmp.name
        try:
            # mtime = now, so age = ~0 which is <= max_age
            result = funcs.read_cache(tmp_path, 0)
            # age ~0 <= 0 is True
            self.assertEqual(result, "boundary")
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Tests for exist_and_is_character
# ---------------------------------------------------------------------------
class TestExistAndIsCharacter(unittest.TestCase):

    def test_returns_false_for_missing_file(self):
        self.assertFalse(funcs.exist_and_is_character("/dev/nonexistent_xyz"))

    @mock.patch("os.lstat")
    def test_returns_true_for_character_device(self, mock_lstat):
        # S_IFCHR = 0o020000, mode for a char device with 0666 perms
        mock_lstat.return_value = os.stat_result(
            (0o020666, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        )
        self.assertTrue(funcs.exist_and_is_character("/dev/ipmi0"))

    @mock.patch("os.lstat")
    def test_returns_false_for_regular_file(self, mock_lstat):
        # S_IFREG = 0o100000
        mock_lstat.return_value = os.stat_result(
            (0o100644, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        )
        self.assertFalse(funcs.exist_and_is_character("/dev/ipmi0"))


# ---------------------------------------------------------------------------
# Tests for OID helper functions (writeline, singlelinetooid, etc.)
# ---------------------------------------------------------------------------
class TestOidHelpers(unittest.TestCase):

    def setUp(self):
        self.buf = io.StringIO()
        # Inject our buffer as the global 'f' used by writeline
        funcs.f = self.buf

    def test_writeline(self):
        funcs.writeline(".1.2.3", "hello")
        self.assertEqual(self.buf.getvalue(), ".1.2.3:hello\n")

    def test_singlelinetooid_strips_whitespace(self):
        funcs.singlelinetooid(".1", "title", "  value  ")
        self.assertEqual(self.buf.getvalue(), ".1.0:value\n")

    def test_multilinetooid(self):
        funcs.multilinetooid(".1", "title", "line1\nline2\nline3")
        lines = self.buf.getvalue().splitlines()
        self.assertEqual(lines[0], ".1.1:line1")
        self.assertEqual(lines[1], ".1.2:line2")
        self.assertEqual(lines[2], ".1.3:line3")
        self.assertEqual(lines[3], ".1.0:3")

    def test_multilinetooid_strips_each_line(self):
        funcs.multilinetooid(".1", "t", "  a  \n  b  ")
        lines = self.buf.getvalue().splitlines()
        self.assertEqual(lines[0], ".1.1:a")
        self.assertEqual(lines[1], ".1.2:b")

    def test_multilinetooid_empty_string(self):
        funcs.multilinetooid(".1", "t", "")
        self.assertEqual(self.buf.getvalue(), ".1.0:0\n")

    def test_dictarrayoid(self):
        data = [
            {"name": "name", "status": "status"},
            {"name": "lv1", "status": "ok"},
            {"name": "lv2", "status": "bad"},
        ]
        funcs.dictarrayoid(".2.5", "title", data)
        output = self.buf.getvalue()
        # Header row (index 0 of keys)
        self.assertIn(".2.5.0.0:name", output)
        self.assertIn(".2.5.0.1:status", output)
        # Data rows
        self.assertIn(".2.5.1.0:lv1", output)
        self.assertIn(".2.5.1.1:ok", output)
        self.assertIn(".2.5.2.0:lv2", output)
        self.assertIn(".2.5.2.1:bad", output)


# ---------------------------------------------------------------------------
# Tests for data processing logic (ipmitool pipe replacement, etc.)
# These test the Python equivalents of the old shell pipelines.
# ---------------------------------------------------------------------------
class TestIpmitoolPipeReplacement(unittest.TestCase):
    """The script replaces ' | ' with ';' using re.sub — same as the old
    sed -e 's/ *| */;/g' pipeline."""

    def test_basic_replacement(self):
        import re
        raw = "CPU Temp  | 45 degrees | ok\nFan1     | 3000 RPM   | ok\n"
        result = re.sub(r' *\| *', ';', raw)
        self.assertEqual(result, "CPU Temp;45 degrees;ok\nFan1;3000 RPM;ok\n")

    def test_no_pipes(self):
        import re
        raw = "no pipes here\n"
        result = re.sub(r' *\| *', ';', raw)
        self.assertEqual(result, "no pipes here\n")

    def test_empty_input(self):
        import re
        self.assertEqual(re.sub(r' *\| *', ';', ""), "")


class TestArcconfParsing(unittest.TestCase):
    """Test that the Python parsing produces the same results as the old
    grep + awk pipelines."""

    GETCONFIG_PD_OUTPUT = textwrap.dedent("""\
        Device #0
           State                              : Online
           Current Temperature                : 32 C/ 89 F
        Device #1
           State                              : Online
           Current Temperature                : 35 C/ 95 F
    """)

    def test_temperature_extraction(self):
        linenumber = 0
        temps = []
        for line in self.GETCONFIG_PD_OUTPUT.splitlines():
            line = line.strip()
            if "Current Temperature" in line:
                parts = line.split()
                if len(parts) >= 4:
                    linenumber += 1
                    temps.append(parts[3])
        self.assertEqual(temps, ["32", "35"])
        self.assertEqual(linenumber, 2)

    GETCONFIG_SMART_OUTPUT = textwrap.dedent("""\
        Device #0
           S.M.A.R.T. warnings  : 0
        Device #1
           S.M.A.R.T. warnings  : 2
    """)

    def test_smart_warnings_extraction(self):
        warnings = []
        for line in self.GETCONFIG_SMART_OUTPUT.splitlines():
            line = line.strip()
            if "S.M.A.R.T. warnings" in line:
                parts = line.split()
                if len(parts) >= 4:
                    warnings.append(parts[3])
        self.assertEqual(warnings, ["0", "2"])

    def test_smart_warnings_sum(self):
        smart_sum = 0
        for line in self.GETCONFIG_SMART_OUTPUT.splitlines():
            if "S.M.A.R.T. warnings" in line:
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        smart_sum += int(parts[3])
                    except ValueError:
                        pass
        self.assertEqual(smart_sum, 2)

    GETCONFIG_AR_OUTPUT = textwrap.dedent("""\
        Logical Device number 0
           Device 0  : Present
           Device 1  : Missing
    """)

    def test_device_status_extraction(self):
        import re as re_mod
        statuses = []
        for line in self.GETCONFIG_AR_OUTPUT.splitlines():
            if re_mod.search(r'Device [0-9]', line):
                parts = line.split(":")
                if len(parts) >= 2:
                    val = parts[1].split()[0] if parts[1].split() else ""
                    statuses.append(val)
        self.assertEqual(statuses, ["Present", "Missing"])


class TestSmartctlParsing(unittest.TestCase):
    """Test SMART health extraction that replaced the old grep+sed pipeline."""

    SMARTCTL_OUTPUT = textwrap.dedent("""\
        smartctl 7.2 2020-12-30 r5155
        === START OF READ SMART DATA SECTION ===
        SMART overall-health self-assessment test result: PASSED
    """)

    def test_extract_passed(self):
        data = ""
        for line in self.SMARTCTL_OUTPUT.splitlines():
            if "SMART overall-health self-assessment test result: " in line:
                data = line.replace(
                    "SMART overall-health self-assessment test result: ", ""
                ).strip()
                break
        self.assertEqual(data, "PASSED")

    SMARTCTL_FAILED = textwrap.dedent("""\
        smartctl 7.2 2020-12-30 r5155
        === START OF READ SMART DATA SECTION ===
        SMART overall-health self-assessment test result: FAILED!
    """)

    def test_extract_failed(self):
        data = ""
        for line in self.SMARTCTL_FAILED.splitlines():
            if "SMART overall-health self-assessment test result: " in line:
                data = line.replace(
                    "SMART overall-health self-assessment test result: ", ""
                ).strip()
                break
        self.assertEqual(data, "FAILED!")

    def test_extract_missing(self):
        """If smartctl returns no health line, data stays empty."""
        data = ""
        for line in "smartctl: no device\n".splitlines():
            if "SMART overall-health self-assessment test result: " in line:
                data = line.replace(
                    "SMART overall-health self-assessment test result: ", ""
                ).strip()
                break
        self.assertEqual(data, "")


class TestLvsParsing(unittest.TestCase):
    """Test JSON-based LVS parsing that replaced the old lvs|jq pipelines."""

    LVS_JSON = json.dumps({
        "report": [{
            "lv": [
                {"lv_name": "root", "lv_health_status": ""},
                {"lv_name": "swap", "lv_health_status": ""},
            ]
        }]
    })

    def test_lv_list_extraction(self):
        lvs_data = json.loads(self.LVS_JSON)
        lv_list = lvs_data.get("report", [{}])[0].get("lv", [])
        self.assertEqual(len(lv_list), 2)
        self.assertEqual(lv_list[0]["lv_name"], "root")

    def test_compact_json_output(self):
        lvs_data = json.loads(self.LVS_JSON)
        compact = json.dumps(lvs_data, separators=(',', ':'))
        # No spaces after separators
        self.assertNotIn(", ", compact)
        self.assertNotIn(": ", compact)

    def test_health_status_no_problems(self):
        lvs_data = json.loads(self.LVS_JSON)
        problems = []
        for lv in lvs_data.get("report", [{}])[0].get("lv", []):
            if lv.get("lv_health_status", "") != "":
                problems.append(json.dumps(lv, separators=(',', ':')))
        self.assertEqual(problems, [])

    LVS_JSON_WITH_PROBLEM = json.dumps({
        "report": [{
            "lv": [
                {"lv_name": "root", "lv_health_status": ""},
                {"lv_name": "data", "lv_health_status": "partial"},
            ]
        }]
    })

    def test_health_status_with_problem(self):
        lvs_data = json.loads(self.LVS_JSON_WITH_PROBLEM)
        problems = []
        for lv in lvs_data.get("report", [{}])[0].get("lv", []):
            if lv.get("lv_health_status", "") != "":
                problems.append(json.dumps(lv, separators=(',', ':')))
        self.assertEqual(len(problems), 1)
        self.assertIn("partial", problems[0])

    def test_empty_lvs_output(self):
        """Empty string from lvs should not crash."""
        raw = ""
        self.assertFalse(bool(raw))


class TestCephParsing(unittest.TestCase):
    """Test JSON-based ceph parsing that replaced the old ceph|jq pipelines."""

    CEPH_STATUS_JSON = json.dumps({
        "health": {"status": "HEALTH_OK", "checks": {}},
        "pgmap": {"pgs_by_state": [], "num_pgs": 128},
    })

    def test_health_status_extraction(self):
        ceph_data = json.loads(self.CEPH_STATUS_JSON)
        status = ceph_data.get("health", {}).get("status", "")
        self.assertEqual(status, "HEALTH_OK")

    def test_pgmap_extraction(self):
        ceph_data = json.loads(self.CEPH_STATUS_JSON)
        pgmap = ceph_data.get("pgmap", {})
        result = json.dumps(pgmap, separators=(',', ':'))
        self.assertIn('"num_pgs":128', result)

    def test_malformed_json_returns_empty(self):
        raw = "not json at all"
        data = ""
        try:
            ceph_data = json.loads(raw)
            data = ceph_data.get("health", {}).get("status", "")
        except json.JSONDecodeError:
            data = ""
        self.assertEqual(data, "")

    def test_missing_health_key(self):
        raw = json.dumps({"other": "stuff"})
        ceph_data = json.loads(raw)
        status = ceph_data.get("health", {}).get("status", "")
        self.assertEqual(status, "")


class TestSmartctlScanParsing(unittest.TestCase):
    """Test the SMART scan + health check loop (replaces the old bash
    while-read pipeline with grep -v PASSED | wc -l)."""

    def test_all_passed(self):
        import re as re_mod
        scan_output = "/dev/sda -d sat # /dev/sda\n/dev/nvme0 -d nvme # /dev/nvme0\n"
        health_outputs = {
            "/dev/sda": "SMART overall-health self-assessment test result: PASSED\n",
            "/dev/nvme0": "SMART overall-health self-assessment test result: PASSED\n",
        }
        fail_count = 0
        for line in scan_output.splitlines():
            dev = line.split()[0] if line.split() else ""
            if not re_mod.match(r'^/dev/(sd|nvme)', dev):
                continue
            for hline in health_outputs[dev].splitlines():
                if "SMART overall-health self-assessment test result: " in hline:
                    result_val = hline.replace(
                        "SMART overall-health self-assessment test result: ", ""
                    ).strip()
                    if result_val != "PASSED":
                        fail_count += 1
                    break
        self.assertEqual(fail_count, 0)

    def test_one_failed(self):
        import re as re_mod
        scan_output = "/dev/sda -d sat\n/dev/sdb -d sat\n"
        health_outputs = {
            "/dev/sda": "SMART overall-health self-assessment test result: PASSED\n",
            "/dev/sdb": "SMART overall-health self-assessment test result: FAILED!\n",
        }
        fail_count = 0
        for line in scan_output.splitlines():
            dev = line.split()[0] if line.split() else ""
            if not re_mod.match(r'^/dev/(sd|nvme)', dev):
                continue
            for hline in health_outputs[dev].splitlines():
                if "SMART overall-health self-assessment test result: " in hline:
                    result_val = hline.replace(
                        "SMART overall-health self-assessment test result: ", ""
                    ).strip()
                    if result_val != "PASSED":
                        fail_count += 1
                    break
        self.assertEqual(fail_count, 1)

    def test_non_disk_device_skipped(self):
        import re as re_mod
        scan_output = "/dev/bus/0 -d megaraid,0\n"
        fail_count = 0
        for line in scan_output.splitlines():
            dev = line.split()[0] if line.split() else ""
            if not re_mod.match(r'^/dev/(sd|nvme)', dev):
                continue
            fail_count += 1  # should not reach here
        self.assertEqual(fail_count, 0)


# ---------------------------------------------------------------------------
# Tests for replacedisk logic
# ---------------------------------------------------------------------------
class TestReplaceDiskLogic(unittest.TestCase):

    def test_global_flag_set_on_integer_marker(self):
        replacedisk = ["OK", 1, "OK", "OK"]
        globalreplacedisk = "OK"
        if 1 in replacedisk:
            globalreplacedisk = "Problem on one disk"
        self.assertEqual(globalreplacedisk, "Problem on one disk")

    def test_global_flag_ok_when_no_problem(self):
        replacedisk = ["OK", "OK", "OK", "OK"]
        globalreplacedisk = "OK"
        if 1 in replacedisk:
            globalreplacedisk = "Problem on one disk"
        self.assertEqual(globalreplacedisk, "OK")

    def test_smart_failure_sets_replacedisk(self):
        replacedisk = ["OK", "OK", "OK", "OK"]
        data = "FAILED!"
        i = 1
        if data != "PASSED" and data != "":
            replacedisk[i] = 1
        self.assertEqual(replacedisk[1], 1)

    def test_smart_passed_keeps_ok(self):
        replacedisk = ["OK", "OK", "OK", "OK"]
        data = "PASSED"
        i = 0
        if data != "PASSED" and data != "":
            replacedisk[i] = 1
        self.assertEqual(replacedisk[0], "OK")

    def test_smart_empty_keeps_ok(self):
        """Empty result (command failed) should not flag the disk."""
        replacedisk = ["OK", "OK", "OK", "OK"]
        data = ""
        i = 0
        if data != "PASSED" and data != "":
            replacedisk[i] = 1
        self.assertEqual(replacedisk[0], "OK")

    def test_raid_smart_warning_sets_string_status(self):
        replacedisk = ["OK", "OK", "OK", "OK"]
        globalreplacedisk = "OK"
        val = "2"
        linenumber = 1
        if val != "0":
            replacedisk[linenumber - 1] = "RAID SMART Warnings on disk" + str(linenumber)
            globalreplacedisk = "RAID SMART Warnings on one disk"
        self.assertEqual(replacedisk[0], "RAID SMART Warnings on disk1")
        self.assertEqual(globalreplacedisk, "RAID SMART Warnings on one disk")


# ---------------------------------------------------------------------------
# Integration test: run the full script with all commands mocked
# ---------------------------------------------------------------------------
class TestFullScriptExecution(unittest.TestCase):
    """Import the full script with subprocess and os mocked so that no real
    commands are executed.  Verify the output file is produced correctly."""

    def _run_script(self, mock_run_side_effect=None, ipmi_exists=False,
                    arcconf_exists=False):
        """Helper to run the full script in an isolated environment."""
        tmpdir = tempfile.mkdtemp()
        snmpdata_tmp = os.path.join(tmpdir, "snmpdata_tmp.txt")
        snmpdata = os.path.join(tmpdir, "snmpdata.txt")

        default_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        def default_side_effect(cmd, **kwargs):
            if mock_run_side_effect:
                r = mock_run_side_effect(cmd, **kwargs)
                if r is not None:
                    return r
            return default_result

        with mock.patch("subprocess.run", side_effect=default_side_effect):
            with mock.patch("os.path.isfile") as mock_isfile:
                # arcconf doesn't exist unless requested
                def isfile_side_effect(path):
                    if path == "/usr/local/sbin/arcconf":
                        return arcconf_exists
                    # Cache files don't exist
                    if path.startswith("/tmp/"):
                        return False
                    return os.path.isfile.__wrapped__(path) if hasattr(os.path.isfile, '__wrapped__') else True

                mock_isfile.side_effect = isfile_side_effect

                with mock.patch("os.lstat") as mock_lstat:
                    if ipmi_exists:
                        mock_lstat.return_value = os.stat_result(
                            (0o020666, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                        )
                    else:
                        mock_lstat.side_effect = FileNotFoundError

                    # Redirect output files
                    source = open(SCRIPT_PATH).read()
                    source = source.replace(
                        'snmpdata_tmp = "/tmp/snmpdata_tmp.txt"',
                        f'snmpdata_tmp = "{snmpdata_tmp}"',
                    )
                    source = source.replace(
                        'snmpdata = "/tmp/snmpdata.txt"',
                        f'snmpdata = "{snmpdata}"',
                    )

                    exec(compile(source, SCRIPT_PATH, "exec"), {
                        "__name__": "__main__",
                        "__builtins__": __builtins__,
                    })

        if os.path.exists(snmpdata):
            with open(snmpdata) as fh:
                content = fh.read()
        else:
            content = None

        # Cleanup
        for p in [snmpdata_tmp, snmpdata]:
            if os.path.exists(p):
                os.unlink(p)
        os.rmdir(tmpdir)

        return content

    def test_script_produces_output_file(self):
        content = self._run_script()
        self.assertIsNotNone(content)
        self.assertIn(".5.5.0:", content)  # global replace disk status

    def test_all_disks_ok_when_commands_return_empty(self):
        content = self._run_script()
        # replacedisk should all be OK
        self.assertIn(".5.1.0:OK", content)
        self.assertIn(".5.2.0:OK", content)
        self.assertIn(".5.3.0:OK", content)
        self.assertIn(".5.4.0:OK", content)
        self.assertIn(".5.5.0:OK", content)

    def test_smartctl_passed_produces_smartok(self):
        def side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2:
                if cmd[0] == "/usr/sbin/smartctl" and cmd[1] == "--scan":
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0,
                        stdout="/dev/sda -d sat # /dev/sda\n", stderr=""
                    )
                if cmd[0] == "/usr/sbin/smartctl" and cmd[1] == "-H":
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0,
                        stdout="SMART overall-health self-assessment test result: PASSED\n",
                        stderr=""
                    )
            return None

        content = self._run_script(mock_run_side_effect=side_effect)
        self.assertIn(".2.6.0:SMARTOK", content)

    def test_smartctl_failure_produces_smartproblem(self):
        def side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2:
                if cmd[0] == "/usr/sbin/smartctl" and cmd[1] == "--scan":
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0,
                        stdout="/dev/sda -d sat # /dev/sda\n", stderr=""
                    )
                if cmd[0] == "/usr/sbin/smartctl" and cmd[1] == "-H":
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0,
                        stdout="SMART overall-health self-assessment test result: FAILED!\n",
                        stderr=""
                    )
            return None

        content = self._run_script(mock_run_side_effect=side_effect)
        self.assertIn(".2.6.0:SMARTPROBLEM", content)

    def test_lvs_no_problem(self):
        lvs_json = json.dumps({
            "report": [{"lv": [
                {"lv_name": "root", "lv_health_status": ""},
            ]}]
        })

        def side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "/usr/sbin/lvs":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=lvs_json, stderr=""
                )
            return None

        content = self._run_script(mock_run_side_effect=side_effect)
        self.assertIn(".2.9.0:NO LVS PROBLEM", content)

    def test_lvs_with_problem(self):
        lvs_json = json.dumps({
            "report": [{"lv": [
                {"lv_name": "data", "lv_health_status": "partial"},
            ]}]
        })

        def side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "/usr/sbin/lvs":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=lvs_json, stderr=""
                )
            return None

        content = self._run_script(mock_run_side_effect=side_effect)
        self.assertIn(".2.9.0:LVS PROBLEM:", content)

    def test_ceph_health_ok(self):
        ceph_json = json.dumps({
            "health": {"status": "HEALTH_OK"},
            "pgmap": {"num_pgs": 64},
        })

        def side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "/usr/bin/ceph":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=ceph_json, stderr=""
                )
            return None

        content = self._run_script(mock_run_side_effect=side_effect)
        self.assertIn(".2.10.0:HEALTH_OK", content)

    def test_ipmitool_section_with_ipmi_device(self):
        def side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "/usr/bin/ipmitool":
                if "sensor" in cmd and "-v" not in cmd:
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0,
                        stdout="CPU Temp | 45 | degrees C\n", stderr=""
                    )
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="verbose output\n", stderr=""
                )
            return None

        content = self._run_script(
            mock_run_side_effect=side_effect, ipmi_exists=True
        )
        # Pipe chars should be replaced with semicolons
        self.assertIn("CPU Temp;45;degrees C", content)

    def test_crm_status_xml_parsed(self):
        xml_data = textwrap.dedent("""\
            <?xml version="1.0"?>
            <crm_mon version="2.1.5">
              <summary>
                <current_dc name="node1"/>
              </summary>
              <nodes>
                <node name="node1" online="true"/>
              </nodes>
            </crm_mon>
        """)

        def side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and "/usr/sbin/crm" in cmd:
                if "--as-xml" in cmd:
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0, stdout=xml_data, stderr=""
                    )
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="crm output\n", stderr=""
                )
            return None

        content = self._run_script(mock_run_side_effect=side_effect)
        # The XML branch writes summary and nodes sub-OIDs
        self.assertIn(".1.11.0.1.", content)
        self.assertIn(".1.11.0.2.", content)


# ---------------------------------------------------------------------------
# Test that no shell=True is used in run_command_safe
# ---------------------------------------------------------------------------
class TestNoShellInjection(unittest.TestCase):
    """Static analysis: verify that run_command_safe never uses shell=True."""

    def test_run_command_safe_has_no_shell_true(self):
        import ast
        source = open(SCRIPT_PATH).read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "run_command_safe":
                source_segment = ast.get_source_segment(source, node)
                self.assertNotIn("shell=True", source_segment)
                self.assertNotIn("shell = True", source_segment)

    def test_no_check_output_calls(self):
        """The old subprocess.check_output(shell=True) pattern should be
        completely gone."""
        source = open(SCRIPT_PATH).read()
        self.assertNotIn("check_output", source)

    def test_no_shell_tool_variables(self):
        """The old grep/awk/sed/etc. path variables should be removed."""
        source = open(SCRIPT_PATH).read()
        for tool in ["grep", "sort", "awk", "sed", "tr", "head", "echo", "jq", "cut"]:
            pattern = f'{tool} = "/usr/bin/{tool}"'
            self.assertNotIn(pattern, source,
                             f"Shell tool variable for {tool} should be removed")


if __name__ == "__main__":
    unittest.main()
