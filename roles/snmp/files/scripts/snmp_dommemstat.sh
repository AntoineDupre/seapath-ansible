#!/bin/bash
# Copyright (C) 2024, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

# Collect virsh dommemstat for each running VM

set -euo pipefail

/usr/bin/virsh --connect qemu:///system list --name | sed '/^$/d' | while read -r i
do
    echo "Domain: '$i'"
    /usr/bin/virsh --connect qemu:///system dommemstat --domain "$i"
done
