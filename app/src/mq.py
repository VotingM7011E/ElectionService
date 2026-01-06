import os, json, uuid
from datetime import datetime, timezone
import pika

EXCHANGE = os.getenv("MQ_EXCHANGE", "events")
EXCHANGE_TYPE = os.getenv("MQ_EXCHANGE_TYPE", "topic")

def _conn():
    return pika.BlockingConnection(pika.URLParameters(os.environ["AMQP_URL"]))

def publish_event(routing_key: str, data: dict, *, event_version: int = 1):
    connection = _conn()
    ch = connection.channel()
    ch.exchange_declare(exchange=EXCHANGE, exchange_type=EXCHANGE_TYPE, durable=True)

    event = {
        "event_type": routing_key,
        "event_version": event_version,
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "producer": os.getenv("SERVICE_NAME", "election-service"),
        "data": data,
    }

    ch.basic_publish(
        exchange=EXCHANGE,
        routing_key=routing_key,
        body=json.dumps(event).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
        ),
    )
    connection.close()
