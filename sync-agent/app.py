import json
import logging
import os
import time
from datetime import datetime, timezone

import redis
import requests

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("sync-agent")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
PROCESSED_STREAM = os.getenv("PROCESSED_STREAM", "sensor:processed")
SYNC_ENDPOINT = os.getenv("SYNC_ENDPOINT", "https://example.com/iot/upload")
API_TOKEN = os.getenv("SYNC_API_TOKEN", "demo-token")
RETRY_SECONDS = int(os.getenv("RETRY_SECONDS", "10"))


class SyncAgent:
    def __init__(self) -> None:
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.last_id = "0-0"

    def network_available(self) -> bool:
        try:
            response = requests.get(SYNC_ENDPOINT, timeout=3)
            return response.status_code < 500
        except requests.RequestException:
            return False

    def upload(self, payload: dict) -> bool:
        headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
        }
        body = {
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "data": payload,
        }
        try:
            response = requests.post(SYNC_ENDPOINT, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.warning("Upload failed: %s", exc)
            return False

    def run(self) -> None:
        logger.info("Starting Sync Agent stream=%s", PROCESSED_STREAM)

        while True:
            if not self.network_available():
                logger.info("Network/API unavailable, retrying in %s seconds", RETRY_SECONDS)
                time.sleep(RETRY_SECONDS)
                continue

            response = self.redis_client.xread({PROCESSED_STREAM: self.last_id}, block=5000, count=50)
            if not response:
                continue

            for _, entries in response:
                for entry_id, fields in entries:
                    payload_str = fields.get("payload", "{}")
                    try:
                        payload = json.loads(payload_str)
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed payload id=%s", entry_id)
                        self.last_id = entry_id
                        continue

                    if self.upload(payload):
                        logger.info("Synced entry id=%s sensor=%s", entry_id, payload.get("sensor_id"))
                        self.last_id = entry_id
                    else:
                        logger.info("Stopping to retry upload from id=%s", entry_id)
                        time.sleep(RETRY_SECONDS)
                        return


def main() -> None:
    while True:
        try:
            SyncAgent().run()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Sync agent error: %s", exc)
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    main()
