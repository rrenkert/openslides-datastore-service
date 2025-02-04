import copy

import pytest

from datastore.shared.di import injector
from datastore.shared.flask_frontend import ERROR_CODES
from datastore.shared.postgresql_backend.sql_read_database_backend_service import (
    MIGRATION_INDEX_NOT_INITIALIZED,
)
from datastore.shared.services import ReadDatabase
from datastore.writer.flask_frontend.routes import WRITE_URL
from tests.util import assert_error_response, assert_response_code
from tests.writer.system.util import assert_model

from .test_write import create_model


@pytest.fixture()
def data():
    yield copy.deepcopy(
        {
            "user_id": 1,
            "information": {},
            "locked_fields": {},
            "events": [{"type": "create", "fqid": "a/1", "fields": {"f": 1}}],
        }
    )


def test_initial_migration_index(
    json_client, data, db_cur, redis_connection, reset_redis_data
):
    create_model(json_client, data, redis_connection, reset_redis_data)

    db_cur.execute("select migration_index from positions where position=%s", [1])
    migration_index = db_cur.fetchone()[0]
    assert migration_index == -1


def test_use_current_migration_index(
    json_client, data, db_connection, db_cur, redis_connection, reset_redis_data
):
    create_model(json_client, data, redis_connection, reset_redis_data)

    # change the migration index and reset the read DB
    db_cur.execute("update positions set migration_index=3 where position=1", [])
    db_connection.commit()
    injector.get(ReadDatabase).current_migration_index = MIGRATION_INDEX_NOT_INITIALIZED

    data["events"][0] = {"type": "update", "fqid": "a/1", "fields": {"f": 2}}
    response = json_client.post(WRITE_URL, [data])
    assert_response_code(response, 201)
    assert_model("a/1", {"f": 2}, 2)

    db_cur.execute("select migration_index from positions where position=%s", [2])
    migration_index = db_cur.fetchone()[0]
    assert migration_index == 3


def test_varying_migration_indices(
    json_client, data, db_connection, db_cur, redis_connection, reset_redis_data
):
    # create two positions
    create_model(json_client, data, redis_connection, reset_redis_data)

    data["events"][0] = {"type": "update", "fqid": "a/1", "fields": {"f": 2}}
    response = json_client.post(WRITE_URL, [data])
    assert_response_code(response, 201)
    assert_model("a/1", {"f": 2}, 2)

    # modify the migration index of the second position and reset the read db
    db_cur.execute("update positions set migration_index=3 where position=2", [])
    db_connection.commit()
    injector.get(ReadDatabase).current_migration_index = MIGRATION_INDEX_NOT_INITIALIZED

    data["events"][0] = {"type": "update", "fqid": "a/1", "fields": {"f": 3}}
    response = json_client.post(WRITE_URL, [data])
    assert_error_response(response, ERROR_CODES.INVALID_DATASTORE_STATE)
    assert_model("a/1", {"f": 2}, 2)


def test_send_migration_index(
    json_client, data, db_cur, redis_connection, reset_redis_data
):
    data["migration_index"] = 3
    create_model(json_client, data, redis_connection, reset_redis_data)

    db_cur.execute("select migration_index from positions where position=%s", [1])
    migration_index = db_cur.fetchone()[0]
    assert migration_index == 3


def test_send_migration_index_not_empty(
    json_client, data, db_cur, redis_connection, reset_redis_data
):
    create_model(json_client, data, redis_connection, reset_redis_data)

    data["events"][0]["fqid"] = "a/2"
    data["migration_index"] = 3
    response = json_client.post(WRITE_URL, [data])
    assert_error_response(response, ERROR_CODES.DATASTORE_NOT_EMPTY)
    assert (
        "Passed a migration index of 3, but the datastore is not empty."
        == response.json["error"]["msg"]
    )

    db_cur.execute("select migration_index from positions where position=%s", [1])
    migration_index = db_cur.fetchone()[0]
    assert migration_index == -1
