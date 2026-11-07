"""Regressions for cold food searches and catalogs awaiting their first seed."""

import asyncio
import csv
import logging
import sqlite3
import threading
from contextlib import suppress

import pytest

from database.food_library.lookup import warm_food_search
from database.food_library.seeding import FoodLibraryPaths, seed_food_library
from svc.app import _periodic_loop, create_app, lifespan, readiness_snapshot
from tests.test_food_log_api import _csv, food_api  # noqa: F401
from tests.test_nutrition_api import api  # noqa: F401


async def _wait_until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=5)


@pytest.fixture
def warm_app(food_api, monkeypatch):
    _client, db, _headers, _today = food_api
    monkeypatch.delenv("SKIP_LLM_LOAD", raising=False)
    monkeypatch.delenv("MAYOS_REQUIRE_PERSISTENT_DATA", raising=False)
    monkeypatch.setenv("MAYOS_DATA_DIR", str(db.catalog_path.parent))
    monkeypatch.setenv("MAYOS_ALERT_SWEEP_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("MAYOS_DAILY_BACKUP_INTERVAL_SECONDS", "0")
    monkeypatch.setattr("database.database_manager.DEFAULT_CURATION_CSV_PATH", db.curation_path)

    async def skip_hosted_model_warmup():
        return None

    monkeypatch.setattr("svc.llm.warmup_llm", skip_hosted_model_warmup)
    return create_app()


def test_startup_prepares_index_before_first_search(warm_app):
    async def scenario():
        async with lifespan(warm_app):
            db = warm_app.state.db
            await _wait_until(lambda: db._food_search_cache is not None)
            cached = db._food_search_cache
            assert "egg" in cached[1]
            assert "hidden" not in cached[1]
            assert readiness_snapshot()[0] == "ready"
            foods = await asyncio.to_thread(db.search_food_library, "hen egg")
            assert [(food["id"], food["name"]) for food in foods] == [("egg", "Egg")]
            assert db._food_search_cache is cached

    asyncio.run(scenario())


def test_startup_stays_ready_and_an_early_search_shares_the_build(warm_app):
    started = threading.Event()
    release = threading.Event()
    request_started = threading.Event()
    builds = []

    def pause_index_read(sql):
        if sql.startswith("SELECT id, name, source_name"):
            builds.append(sql)
            started.set()
            release.wait(timeout=5)

    def search(db):
        request_started.set()
        return db.search_food_library("hen egg")

    async def scenario():
        async with lifespan(warm_app):
            db = warm_app.state.db
            # Trace a real SQLite read to hold the builder at the I/O boundary.
            db.catalog_conn.set_trace_callback(pause_index_read)
            request_task = None
            try:
                assert await asyncio.to_thread(started.wait, 5)
                assert db._food_search_cache is None
                assert readiness_snapshot()[0] == "ready"
                request_task = asyncio.create_task(asyncio.to_thread(search, db))
                assert await asyncio.to_thread(request_started.wait, 5)
                release.set()
                foods = await asyncio.wait_for(request_task, timeout=5)
                assert [food["id"] for food in foods] == ["egg"]
                assert len(builds) == 1
            finally:
                release.set()
                if request_task is not None:
                    await request_task
                await _wait_until(lambda: db._food_search_cache is not None)
                db.catalog_conn.set_trace_callback(None)

    asyncio.run(scenario())


def test_warmup_failure_is_logged_without_changing_readiness(warm_app, food_api, caplog):
    _client, db, _headers, _today = food_api
    with db.catalog_transaction():
        db.catalog_conn.execute("UPDATE foods SET aliases_en_json='invalid-json' WHERE id='egg'")

    async def scenario():
        async with lifespan(warm_app):
            await _wait_until(lambda: any(
                record.name == "svc.app" and "Food search iteration failed" in record.getMessage()
                for record in caplog.records
            ))
            assert readiness_snapshot()[0] == "ready"

    with caplog.at_level(logging.ERROR, logger="svc.app"):
        asyncio.run(scenario())


def test_periodic_refresh_picks_up_an_external_reseed_before_search(food_api, tmp_path):
    client, db, headers, _today = food_api
    paths = FoodLibraryPaths(*(tmp_path / name for name in (
        "foods.csv", "portions.csv", "curation.csv", "recipes.csv",
    )))

    async def scenario():
        task = asyncio.create_task(_periodic_loop(db, 0.01, warm_food_search, "Food search"))
        try:
            await _wait_until(lambda: db._food_search_cache is not None)
            previous_revision = db._food_search_cache[0]
            with paths.curation.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                fields, rows = reader.fieldnames, list(reader)
            for row in rows:
                if row["id"] == "egg":
                    row.update(display_name="Omelette", aliases_en="pan breakfast")
                elif row["id"] == "staple":
                    row["hidden"] = "true"
            _csv(paths.curation, fields, rows)
            # A separate process seeds through its own connection, never the API's lock.
            with sqlite3.connect(db.catalog_path) as writer:
                seed_food_library(writer, paths)
            await _wait_until(lambda: db._food_search_cache[0] != previous_revision)
            cached = db._food_search_cache
            renamed = client.get("/nutrition/foods?q=pan%20breakfast", headers=headers)
            assert renamed.status_code == 200
            assert [(food["id"], food["name"]) for food in renamed.json()["foods"]] == [
                ("egg", "Omelette"),
            ]
            assert client.get("/nutrition/foods?q=hen%20egg", headers=headers).json()["foods"] == []
            chicken = client.get("/nutrition/foods?q=chicken", headers=headers).json()["foods"]
            assert [food["id"] for food in chicken] == ["exact", "prefix", "alias", "contains", "raw"]
            assert db._food_search_cache is cached
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(scenario())


@pytest.mark.parametrize("revision_table_exists", [False, True])
def test_unseeded_catalog_search_is_empty_and_warns_once(api, caplog, revision_table_exists):
    client, db = api
    if revision_table_exists:
        with db.catalog_transaction():
            db.catalog_conn.execute(
                "CREATE TABLE food_search_revision (id INTEGER PRIMARY KEY, counter INTEGER NOT NULL)"
            )
            db.catalog_conn.execute("INSERT INTO food_search_revision VALUES (1, 10)")
    registered = client.post("/auth/register", json={
        "trainee_id": "unseeded-player", "password": "correct-horse-1",
    }).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    with caplog.at_level(logging.WARNING, logger="database.food_library.lookup"):
        for query in ("egg", "", "chicken"):
            response = client.get("/nutrition/foods", params={"q": query}, headers=headers)
            assert response.status_code == 200
            assert response.json()["foods"] == []
            warm_food_search(db)
    warnings = [record for record in caplog.records
                if record.name == "database.food_library.lookup" and record.levelno == logging.WARNING]
    assert len(warnings) == 1
