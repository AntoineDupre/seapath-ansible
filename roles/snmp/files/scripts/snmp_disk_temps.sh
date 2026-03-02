#!/bin/bash
# Copyright (C) 2024, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

# Collect disk temperatures via smartctl

set -euo pipefail

/usr/sbin/smartctl --scan | awk '{ print $1 }' | while read -r i; do
    temp=$(/usr/sbin/smartctl -a "$i" | grep Temperature_Celsius | awk '{ print $10 }')
    if [ -n "$temp" ]; then
        echo "$i;$temp"
    fi
done
