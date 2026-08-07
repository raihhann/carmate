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
import io
import platform
import subprocess
from functools import lru_cache

from flask import Flask, request, send_file, jsonify
import speech_recognition as sr

from uprotocol.communication.calloptions import CallOptions
from uprotocol.communication.inmemoryrpcclient import InMemoryRpcClient
from uprotocol.communication.upayload import UPayload
from uprotocol.v1.uattributes_pb2 import UPayloadFormat
from uprotocol.v1.uri_pb2 import UUri

import common_uuri
from up_transport_zenoh.uptransportzenoh import UPTransportZenoh

# -----------------------------
# Zenoh transport
# -----------------------------
source = UUri(authority_name="voice-command", ue_id=18)
transport = UPTransportZenoh.new(common_uuri.get_zenoh_config(), source)

async def send_rpc_request_to_zenoh(data):
    try:
        uuri = common_uuri.create_method_uri()
        payload = UPayload(format=UPayloadFormat.UPAYLOAD_FORMAT_TEXT, data=data.encode("utf-8"))
        print(f"[DEBUG] Sending RPC request to {uuri} with payload: '{data}'")
        rpc_client = InMemoryRpcClient(transport)
        options = CallOptions(timeout=60000)
        response_payload = await rpc_client.invoke_method(uuri, payload, options)

        print(f"[DEBUG] Raw RPC response: {response_payload}")

        if response_payload and response_payload.data:
            try:
                decoded = response_payload.data.decode("utf-8")
                print(f"[DEBUG] Decoded RPC response: {decoded}")
                return decoded   # 🔥 RETURN STRING DIRECTLY
            except Exception as e:
                print(f"[ERROR] decode failed: {e}")
                return ""
        else:
            print("[ERROR] Empty RPC response")
            return ""
    except Exception as e:
        print(f"[EXCEPTION] send_rpc_request_to_zenoh failed: {e}")
        raise

# -----------------------------
# Global STT recognizer
# -----------------------------
r = sr.Recognizer()

# -----------------------------
# Flask app
# -----------------------------
app = Flask(__name__, static_url_path="/static", static_folder="static")

def _is_linux() -> bool:
    return platform.system().lower() == "linux"

@lru_cache(maxsize=64)
def _espeak_tts_bytes_cached(text: str, voice: str = "en-us", rate: int = 150) -> bytes:
    cmd = ["espeak", "-v", voice, "-s", str(rate), "--stdout", text]
    try:
        res = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        print(f"[DEBUG] TTS generated {len(res.stdout)} bytes for text: '{text}'")
        return res.stdout
    except FileNotFoundError:
        raise RuntimeError("espeak is not installed or not found in PATH.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("TTS timeout – text too long or system busy?")
    except subprocess.CalledProcessError as e:
        msg = e.stderr.decode(errors="ignore")[:200]
        raise RuntimeError(f"TTS failed (espeak): {msg}")

# -----------------------------
# Routes
# -----------------------------
@app.route("/")
def root():
    print("[DEBUG] GET / -> serving index.html")
    return app.send_static_file("index.html")

@app.route("/stt", methods=["POST"])
def stt():
    print("[DEBUG] Received /stt POST request")
    if "audio" not in request.files:
        print("[ERROR] No 'audio' file part found")
        return jsonify({"error": "No 'audio' file part found"}), 400

    f = request.files["audio"]
    if f.filename == "":
        print("[ERROR] Empty filename submitted")
        return jsonify({"error": "Empty filename"}), 400

    audio_bytes = f.read()
    audio_file = io.BytesIO(audio_bytes)
    print(f"[DEBUG] Audio file size: {len(audio_bytes)} bytes")

    try:
        with sr.AudioFile(audio_file) as source_audio:
            audio_data = r.record(source_audio)
        text = r.recognize_google(audio_data, language="en-US")
        print(f"[DEBUG] STT result: '{text}'")
        return jsonify({"text": text})
    except sr.UnknownValueError:
        print("[WARNING] STT could not understand audio")
        return jsonify({"text": "", "message": "Could not understand audio"}), 200
    except sr.RequestError as e:
        print(f"[ERROR] STT API error: {e}")
        return jsonify({"error": f"STT API error: {e}"}), 502
    except Exception as e:
        print(f"[EXCEPTION] STT failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/rpc", methods=["POST"])
def rpc():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    print(f"[DEBUG] Received RPC text request: {text}")

    # Send to Zenoh
    answer_text = asyncio.run(send_rpc_request_to_zenoh(text))

    print(f"[DEBUG] RPC Final Answer: {answer_text}")

    return jsonify({"text": answer_text})

@app.route("/tts", methods=["POST"])
def tts():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    print(f"[DEBUG] Received /tts request with text: '{text}'")

    if not text:
        print("[ERROR] No text provided for TTS")
        return jsonify({"error": "No text provided"}), 400

    if len(text) > 2000:
        print(f"[WARNING] Text too long for TTS ({len(text)} chars)")
        return jsonify({"error": "Text too long (max 2000 chars)."}), 413

    voice = data.get("voice", "en-us")
    try:
        rate = int(data.get("rate", 150))
    except Exception:
        rate = 150
    print(f"[DEBUG] Using voice='{voice}', rate={rate}")

    try:
        wav_bytes = _espeak_tts_bytes_cached(text, voice=voice, rate=rate)
        return send_file(
            io.BytesIO(wav_bytes),
            mimetype="audio/wav",
            as_attachment=False,
            download_name="tts.wav",
        )
    except RuntimeError as e:
        print(f"[ERROR] TTS failed: {e}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        print(f"[EXCEPTION] Unexpected TTS error: {e}")
        return jsonify({"error": f"Unexpected TTS error: {e}"}), 500

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    print("[DEBUG] Starting Flask server on 0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)