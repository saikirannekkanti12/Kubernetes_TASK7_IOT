import json
import logging
import os
import statistics
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import redis

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("processor")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
RAW_STREAM = os.getenv("RAW_STREAM", "sensor:raw")
PROCESSED_STREAM = os.getenv("PROCESSED_STREAM", "sensor:processed")
FILTER_MIN = float(os.getenv("FILTER_MIN", "-1000"))
FILTER_MAX = float(os.getenv("FILTER_MAX", "1000"))
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "10"))


class SensorProcessor:
    def __init__(self) -> None:
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))
        self.last_id = "0-0"

    def parse_value(self, payload: str) -> tuple[str, float] | None:
        try:
            data = json.loads(payload)
            sensor_id = str(data.get("sensor_id", "unknown"))
            value = float(data["value"])
            return sensor_id, value
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def process_message(self, fields: dict[str, str]) -> dict | None:
        parsed = self.parse_value(fields.get("payload", ""))
        if not parsed:
            return None

        sensor_id, value = parsed
        if value < FILTER_MIN or value > FILTER_MAX:
            logger.warning("Filtered out-of-range value sensor=%s value=%s", sensor_id, value)
            return None

        values = self.history[sensor_id]
        values.append(value)
        avg_value = statistics.fmean(values)

        return {
            "sensor_id": sensor_id,
            "raw_value": value,
            "window_avg": round(avg_value, 3),
            "window_size": len(values),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "source_topic": fields.get("topic", "unknown"),
        }

    def run(self) -> None:
        logger.info("Starting Processor stream=%s", RAW_STREAM)
        while True:
            response = self.redis_client.xread({RAW_STREAM: self.last_id}, block=5000, count=100)
            if not response:
                continue

            for _, entries in response:
                for entry_id, fields in entries:
                    self.last_id = entry_id
                    result = self.process_message(fields)
                    if not result:
                        continue
                    self.redis_client.xadd(
                        PROCESSED_STREAM,
                        {"payload": json.dumps(result)},
                        maxlen=10000,
                        approximate=True,
                    )
                    logger.info("Processed sensor=%s", result['sensor_id'])


def main() -> None:
    while True:
        try:
            SensorProcessor().run()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Processor error: %s", exc)
            time.sleep(3)


if __name__ == "__main__":
    main()
