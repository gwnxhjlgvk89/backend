import os
import time

from prometheus_client import CollectorRegistry, Gauge, Histogram, generate_latest, multiprocess

POOL_WAIT = Histogram(
    "club_pool_wait_seconds",
    "Time waiting for a transaction connection",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.3, 1, 2, 5),
)
DB_QUERY = Histogram(
    "club_db_query_seconds",
    "Database statement time including lock wait",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.3, 1, 2, 5),
)
CONNECTIONS = Gauge("club_ws_connections", "Current WebSocket connections", multiprocess_mode="livesum")
LOOP_LAG = Gauge("club_event_loop_lag_seconds", "Event loop scheduling delay", multiprocess_mode="livemax")
PASSWORD_WAIT = Histogram(
    "club_password_wait_seconds", "Password work admission wait", buckets=(0.01, 0.1, 0.3, 1, 2, 3, 5, 10, 30)
)
READ_POOL_WAIT = Histogram(
    "club_read_pool_wait_seconds",
    "Identity read pool admission wait",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.3, 1, 2, 3, 5),
)
PASSWORD_EXECUTION = Histogram(
    "club_password_execution_seconds",
    "Native password work duration",
    ["operation"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.3, 1),
)


def render():
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest()


def before_cursor(conn, cursor, statement, parameters, context, executemany):
    context.club_started = time.perf_counter()


def after_cursor(conn, cursor, statement, parameters, context, executemany):
    verb = statement.lstrip().split(" ", 1)[0].upper()
    DB_QUERY.labels(verb if verb in {"SELECT", "INSERT", "UPDATE", "DELETE"} else "OTHER").observe(
        time.perf_counter() - context.club_started
    )
