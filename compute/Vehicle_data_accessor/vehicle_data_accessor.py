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

import asyncio
import time
import threading

import paho.mqtt.client as mqtt

from uprotocol.communication.upayload import UPayload
from uprotocol.transport.builder.umessagebuilder import UMessageBuilder
from uprotocol.v1.uri_pb2 import UUri

from up_transport_zenoh.examples.common_uuri import get_zenoh_default_config
from up_transport_zenoh.uptransportzenoh import UPTransportZenoh

from google.protobuf.wrappers_pb2 import StringValue

import os
import json

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")

def load_config(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

config = load_config(CONFIG_PATH)



# ---------------- ZENOH SETUP ----------------
source = UUri(authority_name="publisher", ue_id=1, ue_version_major=1)
publisher = UPTransportZenoh.new(get_zenoh_default_config(), source)

# ---------------- MQTT CONFIG ----------------
MQTT_BROKER = config.get("mqtt", {}).get("broker", os.getenv("MQTT_BROKER", "localhost"))
MQTT_PORT = config.get("mqtt", {}).get("port", int(os.getenv("MQTT_PORT", 1883)))

TOPICS = config.get("topics", [
    "carla/vehicle/speed",
    "carla/vehicle/lat",
    "carla/vehicle/lon",
    "carla/vehicle/alt",
    "carla/vehicle/wetness",
    "mcu/temperature"
])

# Map topic → resource_id (parsing string hex representations to ints)
raw_topic_map = config.get("topic_map", {
    "carla/vehicle/speed": "0x1001",
    "carla/vehicle/lat": "0x1002",
    "carla/vehicle/lon": "0x1003",
    "carla/vehicle/alt": "0x1004",
    "carla/vehicle/wetness": "0x1005",
    "mcu/temperature": "0x2001"
})

TOPIC_MAP = {
    topic: int(res_id, 16) if isinstance(res_id, str) else res_id 
    for topic, res_id in raw_topic_map.items()
}

# Async queue to pass data to Zenoh loop
queue = asyncio.Queue()

# ---------------- MQTT CALLBACKS ----------------
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT")
    for topic in TOPICS:
        client.subscribe(topic)

def on_message(client, userdata, msg):
    topic = msg.topic
    value = msg.payload.decode()

    print(f"MQTT: {topic} -> {value}")

    # Push into async queue
    asyncio.run_coroutine_threadsafe(
        queue.put((topic, value)),
        loop
    )

# ---------------- MQTT THREAD ----------------
def start_mqtt():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

# ---------------- ZENOH PUBLISH LOOP ----------------
async def publish_to_zenoh():
    while True:
        topic, value = await queue.get()

        # Set resource ID based on topic
        source.resource_id = TOPIC_MAP.get(topic, 0xFFFF)

        # Build message
        builder = UMessageBuilder.publish(source)

        msg = StringValue(value=value)
        payload = UPayload.pack(msg)

        umessage = builder.build_from_upayload(payload)

        # Send
        status = await publisher.send(umessage)

        print(f"Zenoh sent [{topic}] -> {value}, status={status}")

# ---------------- MAIN ----------------
if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    # Start MQTT in separate thread
    threading.Thread(target=start_mqtt, daemon=True).start()

    # Run Zenoh async loop
    loop.run_until_complete(publish_to_zenoh())