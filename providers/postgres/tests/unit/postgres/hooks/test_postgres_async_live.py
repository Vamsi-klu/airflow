#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from airflow.models import Connection
from airflow.providers.common.sql.hooks.handlers import fetch_all_handler
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.providers.common.sql.triggers.sql import SQLExecuteQueryTrigger
from airflow.providers.postgres.hooks.postgres import PostgresHook

from tests_common.test_utils.operators.run_deferrable import execute_operator, run_trigger

LIVE_POSTGRES_DSN = os.environ.get(
    "LIVE_POSTGRES_DSN", "postgresql://airflow:airflow@127.0.0.1:5432/airflow_sql"
)
LIVE_TYPES_SQL = """
SELECT
    1::int AS n,
    12.50::numeric AS amount,
    TIMESTAMPTZ '2024-01-02 03:04:05+00' AS ts,
    DATE '2024-01-02' AS d,
    '12345678-1234-5678-1234-567812345678'::uuid AS uid,
    NULL::text AS note
"""


def _live_postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(LIVE_POSTGRES_DSN, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _live_postgres_available(),
    reason="Live Postgres is not reachable at LIVE_POSTGRES_DSN",
)


@pytest.fixture
def live_postgres_conn(create_connection_without_db):
    create_connection_without_db(
        Connection(
            conn_id="postgres_default",
            conn_type="postgres",
            host="127.0.0.1",
            login="airflow",
            password="airflow",
            schema="airflow_sql",
            port=5432,
        )
    )


@pytest.fixture
def seeded_table(live_postgres_conn):
    hook = PostgresHook(postgres_conn_id="postgres_default")
    hook.run(
        """
        CREATE TABLE IF NOT EXISTS defer_ro (id int);
        DELETE FROM defer_ro;
        """
    )
    return hook


def test_postgres_hook_arun_selects_typed_row(seeded_table):
    hook = seeded_table
    rows = hook.run(LIVE_TYPES_SQL, handler=fetch_all_handler)
    async_rows = asyncio.run(hook.arun(LIVE_TYPES_SQL, handler=fetch_all_handler, read_only=True))
    assert rows == async_rows
    row = rows[0]
    assert row[0] == 1
    assert row[1] == Decimal("12.50")
    assert row[2] == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert row[4] == UUID("12345678-1234-5678-1234-567812345678")
    assert row[5] is None


def test_postgres_arun_read_only_rejects_insert(seeded_table):
    hook = seeded_table
    with pytest.raises(Exception, match="read-only"):
        asyncio.run(hook.arun("INSERT INTO defer_ro VALUES (1)", handler=None, read_only=True))
    remaining = hook.run("SELECT count(*) FROM defer_ro", handler=fetch_all_handler)
    assert remaining[0][0] == 0


def test_trigger_runs_select_on_live_postgres(live_postgres_conn):
    trigger = SQLExecuteQueryTrigger(
        sql=LIVE_TYPES_SQL,
        conn_id="postgres_default",
        fetch_results=True,
        read_only=True,
    )
    events = run_trigger(trigger)
    assert len(events) == 1
    assert events[0].payload["status"] == "success"
    decoded = SQLExecuteQueryTrigger.deserialize_sql_value(events[0].payload["results"])
    assert decoded[0][0] == 1
    assert decoded[0][1] == Decimal("12.50")
    assert decoded[0][4] == UUID("12345678-1234-5678-1234-567812345678")


def test_operator_deferred_path_matches_sync(live_postgres_conn):
    sync_op = SQLExecuteQueryOperator(
        task_id="sync_select",
        sql=LIVE_TYPES_SQL,
        conn_id="postgres_default",
        deferrable=False,
        do_xcom_push=True,
    )
    sync_result = sync_op.execute({})

    defer_op = SQLExecuteQueryOperator(
        task_id="defer_select",
        sql=LIVE_TYPES_SQL,
        conn_id="postgres_default",
        deferrable=True,
        enforce_read_only=True,
        do_xcom_push=True,
    )
    defer_result, events = execute_operator(defer_op)
    assert events
    assert events[0].payload["status"] == "success"
    assert defer_result == sync_result
    assert defer_result[0][1] == Decimal("12.50")


def test_operator_rejects_write_before_defer(live_postgres_conn):
    op = SQLExecuteQueryOperator(
        task_id="write_guard",
        sql="INSERT INTO defer_ro VALUES (1)",
        conn_id="postgres_default",
        deferrable=True,
        enforce_read_only=True,
    )
    with pytest.raises(ValueError, match="appears to contain a write"):
        op.execute({})
