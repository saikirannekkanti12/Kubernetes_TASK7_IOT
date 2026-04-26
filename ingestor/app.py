import json
import logging
import os
import socket
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import redis

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("ingestor")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
RAW_STREAM = os.getenv("RAW_STREAM", "sensor:raw")
MODE = os.getenv("INGEST_MODE", "mqtt")


class StreamWriter:
    def __init__(self) -> None:
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    def write(self, payload: dict) -> None:
        self.redis_client.xadd(RAW_STREAM, payload, maxlen=10000, approximate=True)


writer = StreamWriter()


def on_connect(client, userdata, flags, reason_code, properties=None):
    topic = os.getenv("MQTT_TOPIC", "sensors/#")
    logger.info("Connected to MQTT broker, subscribing to %s", topic)
    client.subscribe(topic)


def on_message(client, userdata, msg):
    now = datetime.now(timezone.utc).isoformat()
    try:
        body = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        body = {"raw": msg.payload.decode("utf-8", errors="replace")}

    payload = {
        "topic": msg.topic,
        "received_at": now,
        "payload": json.dumps(body),
    }
    writer.write(payload)
    logger.info("Ingested MQTT message from topic=%s", msg.topic)


def run_mqtt() -> None:
    host = os.getenv("MQTT_HOST", "mosquitto")
    port = int(os.getenv("MQTT_PORT", "1883"))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    logger.info("Connecting MQTT host=%s port=%s", host, port)
    client.connect(host, port, keepalive=60)
    client.loop_forever()


def run_socket() -> None:
    socket_path = os.getenv("SOCKET_PATH", "/tmp/sensors.sock")
    buffer_size = int(os.getenv("SOCKET_BUFFER", "4096"))

    if os.path.exists(socket_path):
        os.remove(socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(5)
    logger.info("Listening on local socket %s", socket_path)

    while True:
        conn, _ = server.accept()
        with conn:
            raw = conn.recv(buffer_size).decode("utf-8")
            if not raw:
                continue
            payload = {
                "topic": "local-socket",
                "received_at": datetime.now(timezone.utc).isoformat(),
                "payload": raw,
            }
            writer.write(payload)
            logger.info("Ingested local socket payload")


def main() -> None:
    logger.info("Starting Data Ingestor in mode=%s", MODE)
    while True:
        try:
            if MODE == "socket":
                run_socket()
            else:
                run_mqtt()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ingestor error: %s", exc)
            time.sleep(3)


if __name__ == "__main__":
    main()
