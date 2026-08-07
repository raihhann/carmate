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

FROM python:3.11-slim

WORKDIR /app

# Install system libraries essential for CARLA's C++ components to run in Python
RUN apt-get update && apt-get install -y \
    libpng16-16 \
    libjpeg62-turbo \
    libtiff6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your script into the container workspace
COPY carla_provider.py .
COPY config.json .

# By using CMD instead of ENTRYPOINT, we can set a default behavior.
# This defaults the container to run in MOCK mode out of the box:
CMD ["python", "carla_provider.py", "--nocarla"]