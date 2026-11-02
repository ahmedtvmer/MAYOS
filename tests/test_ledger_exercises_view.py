from database.exercise_resolution import exercise_display_join


def test_ledger_exercises_view_join_is_flattenable(fresh_store):
    ledger = fresh_store.ledger
    query = (
        "SELECT pe.exercise_id, e.name FROM "
        f"(SELECT exercise_id FROM program_exercises) pe "
        f"{exercise_display_join('pe.exercise_id')}"
    )
    plan = " ".join(
        str(row[3])
        for row in ledger.conn.execute("EXPLAIN QUERY PLAN " + query).fetchall()
    ).upper()

    assert "MATERIALIZE" not in plan
    assert "SCAN E" not in plan
    assert "SEARCH E USING" in plan
    assert "(ID=?)" in plan


def test_ledger_exercises_view_uses_display_name_then_catalog_name(fresh_store):
    ledger = fresh_store.ledger
    catalog = fresh_store.catalog_conn
    exercise_ids = [
        row[0]
        for row in catalog.execute("SELECT id FROM exercises ORDER BY id LIMIT 2")
    ]
    assert len(exercise_ids) == 2
    display_id, fallback_id = exercise_ids
    catalog.execute(
        "UPDATE exercises SET name = ? WHERE id = ?", ("Catalog fallback", fallback_id)
    )
    catalog.execute("DELETE FROM exercise_display_names WHERE exercise_id = ?", (fallback_id,))
    catalog.execute(
        "INSERT OR REPLACE INTO exercise_display_names (exercise_id, display_name) "
        "VALUES (?, ?)",
        (display_id, "Preferred display"),
    )
    catalog.commit()

    names = dict(
        ledger.conn.execute(
            "SELECT id, name FROM exercises WHERE id IN (?, ?)",
            (display_id, fallback_id),
        ).fetchall()
    )

    assert names[display_id] == "Preferred display"
    assert names[fallback_id] == "Catalog fallback"


def test_raw_catalog_write_advances_program_cache_revision(fresh_store):
    catalog = fresh_store.catalog_conn
    before = catalog.execute(
        "SELECT counter FROM program_revision WHERE id=1"
    ).fetchone()[0]
    exercise_id = catalog.execute("SELECT id FROM exercises ORDER BY id LIMIT 1").fetchone()[0]
    catalog.execute("UPDATE exercises SET name=name WHERE id=?", (exercise_id,))
    catalog.commit()

    after = catalog.execute(
        "SELECT counter FROM program_revision WHERE id=1"
    ).fetchone()[0]
    assert after == before + 1
