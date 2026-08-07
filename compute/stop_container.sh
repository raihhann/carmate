# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * See the NOTICE file(s) distributed with this work for additional
# * information regarding copyright ownership.
# *
# * This program and the accompanying materials are made available under the
# * terms of the Apache License 2.0 which is available at
# * https://www.apache.org/licenses/LICENSE-2.0
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

#!/bin/bash

echo "🧹 FULL MQTT CLEANUP (NO RESTART LOOP)"

sudo docker compose down

echo "🛑 Stopping system services (IMPORTANT)"
sudo systemctl stop mosquitto
sudo systemctl disable mosquitto

sudo systemctl stop dnsmasq
sudo systemctl disable dnsmasq

echo "🔪 Killing leftover processes"
sudo pkill -9 mosquitto
sudo pkill -9 dnsmasq

echo "🔍 Checking port 1883"
sudo lsof -i :1883

echo "✅ Done"