"""Behaviour tests for normal plans, injection handling and batch isolation."""

import sqlite3

import pytest

from query.binder import build_select, expand_in, query_batch

SAFE_POLICY = {
    "allow_string_concat": False,
    "identifier_whitelist": True,
    "max_rows": 1000,
}


def test_normal_condition_query_plan():
    plan = build_select(
        "users",
        ["id", "name"],
        {"status": "active"},
        ("created_at", "DESC"),
        25,
    )

    assert plan == {
        "sql": (
            "SELECT `id`, `name` FROM `users` "
            "WHERE `status` = ? ORDER BY `created_at` DESC LIMIT ?"
        ),
        "params": ("active", 25),
    }


def test_injection_string_is_data_in_memory():
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
        )
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?)",
            (1, "alice", "active"),
        )

        injection = "x' OR 1=1 --"
        plan = build_select(
            "users",
            ["id", "name"],
            {"name": injection},
            None,
            10,
        )
        rows = connection.execute(plan["sql"], plan["params"]).fetchall()

        assert rows == []
    finally:
        connection.close()


def test_non_whitelisted_column_is_rejected():
    with pytest.raises(ValueError):
        build_select("users", ["id", "password"], None, None, 5)


def test_expand_in_placeholder_count():
    values = (10, 20, 30, 40)

    markers = expand_in(values)

    assert len(markers) == len(values) == 4
    assert markers == ("?", "?", "?", "?")


def test_two_batches_match_separate_builds():
    plans = [
        {
            "table": "users",
            "columns": ["id"],
            "where": {"status": "active"},
            "order": None,
            "limit": 5,
        },
        {
            "table": "orders",
            "columns": ["id", "total"],
            "where": {"user_id": 7},
            "order": ("created_at", "ASC"),
            "limit": 10,
        },
    ]

    expected = [build_select(**spec) for spec in plans]
    first = query_batch(plans, SAFE_POLICY)
    second = query_batch(plans, SAFE_POLICY)

    assert first == {"plans": expected, "issues": []}
    assert second == first
