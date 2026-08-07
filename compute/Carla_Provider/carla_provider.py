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

import argparse
import carla
import time
import math
import random
import paho.mqtt.client as mqtt
import json
import os

# -------------------------------
# Load External Configuration
# -------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

try:
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"Error: Configuration file not found at {CONFIG_PATH}")
    exit(1)

# CARLA Configuration (Supports ENV overrides)
CARLA_HOST = os.getenv('CARLA_HOST', config['carla']['host'])
CARLA_PORT = int(os.getenv('CARLA_PORT', config['carla']['port']))
TM_PORT = int(os.getenv('TM_PORT', config['carla']['tm_port']))

# MQTT Configuration (Supports ENV overrides)
MQTT_BROKER = os.getenv('MQTT_BROKER', config['mqtt']['broker'])
MQTT_PORT = int(os.getenv('MQTT_PORT', config['mqtt']['port']))

# MQTT Topics
MQTT_TOPIC_SPEED = config['mqtt']['topics']['speed']
MQTT_TOPIC_LAT = config['mqtt']['topics']['lat']
MQTT_TOPIC_LON = config['mqtt']['topics']['lon']
MQTT_TOPIC_ALT = config['mqtt']['topics']['alt']
MQTT_TOPIC_WETNESS = config['mqtt']['topics']['wetness']

# -------------------------------
# Helper functions
# -------------------------------
def velocity_to_speed_kmh(vel):
    return math.sqrt(vel.x**2 + vel.y**2 + vel.z**2) * 3.6

def mqtt_publish(client, topic, value):
    client.publish(topic, str(value))

# -------------------------------
# Command Line Arguments
# -------------------------------
parser = argparse.ArgumentParser(description="CARLA MQTT Bridge with Mock Data Option")
parser.add_argument('--nocarla', action='store_true', help="Run in mock mode without CARLA simulator")
args = parser.parse_args()

# -------------------------------
# Connect to MQTT
# -------------------------------
mqtt_client = mqtt.Client()
mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
mqtt_client.loop_start()
print(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")

# -------------------------------
# Setup & CARLA Connection (with Retry logic)
# -------------------------------
world = None
settings = None
vehicle = None
gnss_sensor = None
gnss_data = {"lat": 0.0, "lon": 0.0, "alt": 0.0}

def gnss_callback(measurement):
    gnss_data["lat"] = measurement.latitude
    gnss_data["lon"] = measurement.longitude
    gnss_data["alt"] = measurement.altitude

# Only attempt CARLA connection if --nocarla is NOT specified
if not args.nocarla:
    max_retries = 2
    retry_delay = 10 # seconds
    client = None

    for attempt in range(1, max_retries + 1):
        try:
            print(f"Connecting to CARLA at {CARLA_HOST}:{CARLA_PORT} (Attempt {attempt}/{max_retries})...")
            client = carla.Client(CARLA_HOST, CARLA_PORT)
            client.set_timeout(10.0)
            world = client.get_world()
            print("Successfully connected to CARLA.")
            break # Exit loop if successful
        except RuntimeError as e:
            print(f"CARLA connection failed: {e}")
            if attempt < max_retries:
                print(f"Waiting {retry_delay} seconds before retrying...")
                time.sleep(retry_delay)
            else:
                print("Could not connect to CARLA after max retries. Exiting.")
                mqtt_client.loop_stop()
                exit(1)

    # Configure Synchronous mode
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)

    # Blueprints and spawn points
    blueprints = world.get_blueprint_library()
    spawn_points = world.get_map().get_spawn_points()

    # Spawn vehicle
    if spawn_points:
        bp = blueprints.find("vehicle.mercedes.coupe_2020")
        vehicle = world.spawn_actor(bp, spawn_points[0])
        vehicle.set_autopilot(True, TM_PORT)
        print(f"Vehicle spawned: {bp.id}, autopilot enabled on TM port {TM_PORT}")
    else:
        raise RuntimeError("No spawn points found in CARLA map")

    # Attach GNSS sensor
    gnss_bp = blueprints.find("sensor.other.gnss")
    gnss_bp.set_attribute("sensor_tick", "0.05")
    gnss_transform = carla.Transform(carla.Location(x=0.0, y=0.0, z=1.8))
    gnss_sensor = world.spawn_actor(gnss_bp, gnss_transform, attach_to=vehicle)
    gnss_sensor.listen(gnss_callback)

else:
    print("--- Running in MOCK mode (--nocarla activated) ---")
    # Initialize some baseline mock data coordinates (roughly matching a real-world city location)
    mock_lat = 49.0069
    mock_lon = 8.4037
    mock_alt = 115.0

# -------------------------------
# Main loop: Real or Mock telemetry stream
# -------------------------------
cnt = 0
direction_up = True

try:
    while True:
        # Animate wetness 0..20
        if direction_up:
            cnt += 1
            if cnt >= 20:
                direction_up = False
        else:
            cnt -= 1
            if cnt <= 0:
                direction_up = True
                cnt = 0
        wetness = cnt

        if not args.nocarla:
            # === CARLA REAL MODE ===
            world.tick()  # advance simulation

            # Read real telemetry
            speed = velocity_to_speed_kmh(vehicle.get_velocity())
            lat, lon, alt = gnss_data["lat"], gnss_data["lon"], gnss_data["alt"]
        else:
            # === MOCK MODE ===
            # Generate slight random fluctuations to simulate motion
            speed = random.uniform(30.0, 50.0) # mock speed between 30 and 50 km/h
            mock_lat += random.uniform(-0.00001, 0.00001)
            mock_lon += random.uniform(-0.00001, 0.00001)
            mock_alt += random.uniform(-0.1, 0.1)
            
            lat, lon, alt = mock_lat, mock_lon, mock_alt

        # Publish data to MQTT (Runs identically for both real and mock data)
        mqtt_publish(mqtt_client, MQTT_TOPIC_SPEED, speed)
        mqtt_publish(mqtt_client, MQTT_TOPIC_LAT, lat)
        mqtt_publish(mqtt_client, MQTT_TOPIC_LON, lon)
        mqtt_publish(mqtt_client, MQTT_TOPIC_ALT, alt)
        mqtt_publish(mqtt_client, MQTT_TOPIC_WETNESS, wetness)

        print(f"[{'MOCK' if args.nocarla else 'REAL'}] Speed: {speed:.1f} km/h | lat: {lat:.6f}, lon: {lon:.6f}, alt: {alt:.1f} m | Wetness: {wetness} %")

        time.sleep(0.05)  # Maintain tick rate loop pace

except KeyboardInterrupt:
    print("\nSimulation stopped by user")

finally:
    # Cleanup CARLA assets only if we weren't running mock server
    if not args.nocarla:
        if gnss_sensor is not None:
            gnss_sensor.stop()
            gnss_sensor.destroy()
        if vehicle is not None:
            vehicle.destroy()

        if world is not None:
            settings = world.get_settings()
            settings.synchronous_mode = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)
        print("Vehicle destroyed and world restored to async mode")
        
    mqtt_client.loop_stop()
    print("MQTT connection closed safely.")