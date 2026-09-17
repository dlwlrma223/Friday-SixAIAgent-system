"""Postgres connection pool for the agent.

Same env variable names as the api service so both read one config.
"""

import os
from pathlib import Path

from psycopg_pool import ConnectionPool

# Same public AWS CA bundle the api uses; verify-full when present.
RDS_CA_BUNDLE = Path(__file__).resolve().parent.parent / "certs" / "rds-global-bundle.pem"


def build_conninfo(env: dict[str, str] | None = None) -> str:
    env = env if env is not None else dict(os.environ)
    parts = {
        "host": env.get("DB_HOST", "localhost"),
        "port": env.get("DB_PORT", "5432"),
        "user": env.get("DB_USER", ""),
        "password": env.get("DB_PASSWORD", ""),
        "dbname": env.get("DB_NAME", ""),
        "connect_timeout": "5",
    }
    if env.get("DB_SSL") == "disable":
        parts["sslmode"] = "disable"
    elif RDS_CA_BUNDLE.exists():
        parts["sslmode"] = "verify-full"
        parts["sslrootcert"] = str(RDS_CA_BUNDLE)
    else:
        parts["sslmode"] = "require"
    return " ".join(f"{k}={v}" for k, v in parts.items() if v != "")


def build_pool(max_size: int | None = None) -> ConnectionPool:
    # Small cap: db.t4g.micro allows ~80 connections total across all services.
    size = max_size or int(os.environ.get("DB_POOL_MAX", "5"))
    return ConnectionPool(build_conninfo(), min_size=1, max_size=size, open=True)
