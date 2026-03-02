#!/bin/bash
# Copyright (C) 2024, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

# Collect virsh domstats for all VMs

set -euo pipefail

/usr/bin/virsh --connect qemu:///system domstats
