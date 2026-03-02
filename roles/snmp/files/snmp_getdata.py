#!/usr/bin/python3
# Copyright (C) 2024, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import subprocess,json,os,stat,re,time
import xmltodict
from xml.parsers.expat import ParserCreate, ExpatError, errors

def run_command_safe(command_list, timeout=30):
    """Run a command without shell=True. Returns stdout or empty string on failure."""
    try:
        result = subprocess.run(
            command_list,
            capture_output=True, text=True, check=False, timeout=timeout,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""

def run_shell_command(command, timeout=30):
    """Run a shell command (for pipes). Returns stdout or empty string on failure."""
    try:
        result = subprocess.run(
            command, shell=True, executable='/bin/bash',
            capture_output=True, text=True, check=False, timeout=timeout,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""

def read_cache(cache_file, max_age):
    """Read a cache file if it exists and is fresh enough. Returns content or None."""
    if os.path.isfile(cache_file):
        if (time.time() - os.path.getmtime(cache_file)) <= max_age:
            with open(cache_file) as cf:
                return cf.read()
    return None

def write_cache(cache_file, data):
    """Write data to a cache file."""
    with open(cache_file, "w") as cf:
        cf.write(data)

def writeline(oid,line):
    f.write(oid + ":" + line + "\n")

def singlelinetooid(oid,title,line):
    line = line.lstrip().rstrip()
    writeline(oid + ".0", line)

def multilinetooid(oid,title,multistr):
    linenumber = 0
    for line in multistr.splitlines():
        linenumber = linenumber + 1
        line = line.lstrip().rstrip()
        writeline(oid + "." + str(linenumber), line)
    writeline(oid + ".0", str(linenumber))

def dictarrayoid(oid,title,a):
    keys = list(a[0].keys())
    for key in keys:
        writeline(oid + ".0." + str(keys.index(key)), key)
    for d in a[1:]:
        for k in range(0,len(d)):
            writeline(oid + "." + str(a.index(d)) + "." + str(k), d[keys[k]])

base_oid = ""
snmpdata_tmp = "/tmp/snmpdata_tmp.txt"
snmpdata = "/tmp/snmpdata.txt"
f = open(snmpdata_tmp, "w")

# .1 --> "other" multiline values
# .2 --> "other" monoline values
# .3 --> raid/arcconf values
# .4 --> ipmitool values
# .5 --> global "disk need to be replaced" values

# Disk needs to be replaced logic
# We assume the server may have up to 4 disks, and while running this script we will keep in mind if any check is a hint the disk needs to be replaces (with the RAID tests, then the SMART tests and then the LVM tests).
# We start with a "no pb" status and toggle to "not ok" if needed
globalreplacedisk = "OK" # we store a global status, including a problem detected on LVM for example
replacedisk = ["OK","OK","OK","OK"] # we store a status per disk

#IPMITOOL
ipmitool = "/usr/bin/ipmitool"
def exist_and_is_character(filepath):
    try:
        r = stat.S_ISCHR(os.lstat(filepath)[stat.ST_MODE])
    except FileNotFoundError:
        return False
    return r

if exist_and_is_character("/dev/ipmi0") or exist_and_is_character("/dev/ipmi/0") or exist_and_is_character("/dev/ipmidev/0"):
    for i in range(1,5):
        if i == 1:
            title = "ipmitool sensor"
            raw = run_command_safe([ipmitool, "sensor"])
            data = re.sub(r' *\| *', ';', raw)
        elif i == 2:
            title = "ipmitool sensor verbose"
            data = run_command_safe([ipmitool, "sensor", "-v"])
        elif i == 3:
            title = "ipmitool sdr"
            raw = run_command_safe([ipmitool, "sdr", "list"])
            data = re.sub(r' *\| *', ';', raw)
        elif i == 4:
            title = "ipmitool sdr verbose"
            data = run_command_safe([ipmitool, "sdr", "list", "-v"])
        multilinetooid(base_oid + ".4." + str(i), title, data)

# RAID
arcconf = "/usr/local/sbin/arcconf"
if os.path.isfile(arcconf):
    # get temperatures
    raw = run_command_safe([arcconf, "GETCONFIG", "1", "PD"])
    linenumber = 0
    for line in raw.splitlines():
        line = line.strip()
        if "Current Temperature" in line:
            parts = line.split()
            if len(parts) >= 4:
                linenumber = linenumber + 1
                singlelinetooid(base_oid + ".3.1."+str(linenumber), "temperature disk " + str(linenumber), parts[3])

    raw = run_command_safe([arcconf, "GETCONFIG", "1"])
    linenumber = 0
    for line in raw.splitlines():
        line = line.strip()
        if "S.M.A.R.T. warnings" in line:
            parts = line.split()
            if len(parts) >= 4:
                linenumber = linenumber + 1
                val = parts[3]
                singlelinetooid(base_oid + ".3.2."+str(linenumber), "SMART Warnings disk " + str(linenumber), val)
                if val != "0":
                    replacedisk[linenumber-1] = "RAID SMART Warnings on disk"+str(linenumber)
                    globalreplacedisk = "RAID SMART Warnings on one disk"

    # Sum of SMART warnings
    raw = run_command_safe([arcconf, "GETCONFIG", "1"])
    smart_sum = 0
    for line in raw.splitlines():
        if "S.M.A.R.T. warnings" in line:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    smart_sum += int(parts[3])
                except ValueError:
                    pass
    title = "ARCCONF sum of SMART WARNINGS"
    data = str(smart_sum)
    singlelinetooid(base_oid + ".3.3", title, data)
    if data != "0" and data != "":
        globalreplacedisk = "RAID SMART Warnings on one disk"

    raw = run_command_safe([arcconf, "GETCONFIG", "1", "AR"])
    linenumber = 0
    for line in raw.splitlines():
        if re.search(r'Device [0-9]', line):
            parts = line.split(":")
            if len(parts) >= 2:
                title = f"RAID array device {linenumber} status"
                linenumber = linenumber + 1
                val = parts[1].split()[0] if parts[1].split() else ""
                singlelinetooid(base_oid + ".3.4."+str(linenumber), title, val)
                if val != "Present":
                    replacedisk[linenumber-1] = 1

    for i in range(0,4):
        raw = run_command_safe([arcconf, "GETCONFIG", "1", "PD", "0", str(i)])
        title = f"ARCCONF SMART WARNINGS device {i+1}"
        data = ""
        for line in raw.splitlines():
            if "S.M.A.R.T. warnings" in line:
                parts = line.split()
                if len(parts) >= 4:
                    data = parts[3]
                break
        data = data.strip()
        if data != "0" and data!="":
            replacedisk[i] = 1
        singlelinetooid(base_oid + ".3.5."+str(i+1)+".1", title, data)


# OTHER MONOLINE VALUES
# .2.[1-4] --> smart self assessement for /dev/sd[a-d]
# .2.5 -->lvs full status
# .2.5.0 --> column name
# .2.5.1 --> first LV data
# .2.5.2 --> second LV data, etc

# >.2.6 --> other monolines

i = 0
for disk in ["sda","sdb","sdc","sdd"]:
    raw = run_command_safe(["/usr/sbin/smartctl", "-H", f"/dev/{disk}"])
    title = f"smartctl /dev/{disk}"
    data = ""
    for line in raw.splitlines():
        if "SMART overall-health self-assessment test result: " in line:
            data = line.replace("SMART overall-health self-assessment test result: ", "").strip()
            break
    if data != "PASSED" and data != "":
        replacedisk[i] = 1
    i = i + 1
    singlelinetooid(base_oid + ".2." + str(i), title, data)

raw = run_command_safe(["/usr/sbin/lvs", "-a", "-o", "+devices,lv_health_status", "--reportformat", "json"])
title = "lvs full status json"
if raw:
    lvs_json = json.loads(raw)
    data = lvs_json.get("report", [{}])[0].get("lv", [])
    dictarrayoid(base_oid + ".2.5", title, data)

for i in range(6,11):
    if i == 6:
        # Check all disks SMART status
        scan_raw = run_command_safe(["/usr/sbin/smartctl", "--scan"])
        title = "disk smartctl status"
        fail_count = 0
        for line in scan_raw.splitlines():
            dev = line.split()[0] if line.split() else ""
            if not re.match(r'^/dev/(sd|nvme)', dev):
                continue
            health_raw = run_command_safe(["/usr/sbin/smartctl", "-H", dev])
            for hline in health_raw.splitlines():
                if "SMART overall-health self-assessment test result: " in hline:
                    result_val = hline.replace("SMART overall-health self-assessment test result: ", "").strip()
                    if result_val != "PASSED":
                        fail_count += 1
                    break
        if fail_count == 0:
            data = "SMARTOK"
        else:
            data = "SMARTPROBLEM"
            globalreplacedisk = "SMART tests not passed"
    elif i == 7:
        raw = run_command_safe(["/usr/sbin/lvs", "-a", "-o", "+devices,lv_health_status", "--reportformat", "json"])
        title = "lvs full status json"
        if raw:
            data = json.dumps(json.loads(raw), separators=(',', ':'))
        else:
            data = ""
    elif i == 8:
        raw = run_command_safe(["/usr/sbin/lvs", "-o", "name,lv_health_status", "--reportformat", "json"])
        title = "lvs basic status json"
        if raw:
            data = json.dumps(json.loads(raw), separators=(',', ':'))
        else:
            data = ""
    elif i == 9:
        raw = run_command_safe(["/usr/sbin/lvs", "-o", "name,lv_health_status", "--reportformat", "json"])
        title = "lvs sumup status"
        data = ""
        if raw:
            lvs_data = json.loads(raw)
            problems = []
            for lv in lvs_data.get("report", [{}])[0].get("lv", []):
                if lv.get("lv_health_status", "") != "":
                    problems.append(json.dumps(lv, separators=(',', ':')))
            if problems:
                data = "LVS PROBLEM: " + "".join(problems)
                globalreplacedisk = "LVS health not OK"
            else:
                data = "NO LVS PROBLEM"
    elif i == 10:
        raw = run_command_safe(["/usr/bin/ceph", "status", "--format", "json-pretty"])
        title = "ceph health status"
        data = ""
        if raw:
            try:
                ceph_data = json.loads(raw)
                data = ceph_data.get("health", {}).get("status", "")
            except json.JSONDecodeError:
                data = ""
    singlelinetooid(base_oid + ".2." + str(i), title, data)

# OTHER MULTILINES VALUES
for i in range(1,12):
    if i == 1:
        title = "/usr/sbin/crm status"
        data = run_command_safe(["/usr/sbin/crm", "status"])
    elif i == 2:
        title = "virsh domstats"
        cached = read_cache("/tmp/domstats.txt", 120)
        if cached is not None:
            data = cached
        else:
            data = run_command_safe(["/usr/local/bin/snmp_domstats.sh"], timeout=120)
            write_cache("/tmp/domstats.txt", data)
    elif i == 3:
        title = "virsh dommemstat"
        cached = read_cache("/tmp/dommemstat.txt", 120)
        if cached is not None:
            data = cached
        else:
            data = run_command_safe(["/usr/local/bin/snmp_dommemstat.sh"], timeout=120)
            write_cache("/tmp/dommemstat.txt", data)
    elif i == 4:
        title = "ceph status"
        data = run_command_safe(["/usr/bin/ceph", "status"])
    elif i == 5:
        title = "virt-df"
        cached = read_cache("/tmp/virt-df.txt", 3600)
        if cached is not None:
            data = cached
        else:
            data = run_command_safe(["/usr/local/bin/virt-df.sh"], timeout=120)
            write_cache("/tmp/virt-df.txt", data)
    elif i == 6:
        title = "virsh list"
        data = run_command_safe(["/usr/bin/virsh", "-c", "qemu:///system", "list", "--all"])
    elif i == 7:
        title = "ceph usage"
        raw = run_command_safe(["/usr/bin/ceph", "status", "--format=json"])
        data = ""
        if raw:
            try:
                ceph_data = json.loads(raw)
                pgmap = ceph_data.get("pgmap", {})
                data = json.dumps(pgmap, separators=(',', ':'))
            except json.JSONDecodeError:
                data = ""
    elif i == 8:
        title = "temperature disks"
        data = run_command_safe(["/usr/local/bin/snmp_disk_temps.sh"])
    elif i == 9:
        title = "smartctl"
        data = run_command_safe(["/usr/local/bin/snmp_smartctl_detail.sh"], timeout=60)
    elif i == 10:
        title = "lvs status"
        data = run_command_safe(["/usr/sbin/lvs", "-a", "-o", "+devices,lv_health_status"])
    elif i == 11:
        title = "crm status json"
        xml_status = run_command_safe(["/usr/sbin/crm", "status", "--as-xml"])
        try:
            dict_status = xmltodict.parse(xml_status, attr_prefix='')
            data = json.dumps(dict_status)
            data1 = json.dumps(dict_status["crm_mon"]["summary"])
            multilinetooid(base_oid + ".1.11.0.1", title + " summary", data1)
            data2 = json.dumps(dict_status["crm_mon"]["nodes"])
            multilinetooid(base_oid + ".1.11.0.2", title + " nodes", data2)
            continue
        except (ExpatError, KeyError):
            data = xml_status


    multilinetooid(base_oid + ".1." + str(i), title, data)

if 1 in replacedisk:
    globalreplacedisk = "Problem on one disk"
for i in range(1,5):
    singlelinetooid(base_oid + ".5." + str(i), "replace disk " + str(i), replacedisk[i-1])
singlelinetooid(base_oid + ".5.5", "replace disk global",globalreplacedisk)

f.close()

os.rename(snmpdata_tmp, snmpdata)
