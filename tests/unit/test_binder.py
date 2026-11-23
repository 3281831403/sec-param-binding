"""Contract tests for the ten binding defects under test."""

import pytest

from query.binder import (
    bind_values,
    build_insert,
    build_select,
    expand_in,
    placeholder,
    query_batch,
    quote_identifier,
    validate_policy,
)

SAFE_POLICY = {
    "allow_string_concat": False,
    "identifier_whitelist": True,
    "max_rows": 1000,
}


def test_value_is_bound_not_interpolated():
    injection = "x' OR 1=1 --"
    assert bind_values((injection,), "qmark") == (injection,)

    plan = build_select("users", ["id"], {"name": injection}, None, 10)

    assert injection not in plan["sql"]
    assert plan["params"] == (injection, 10)


def test_placeholders_are_positional_not_value_formatted():
    assert placeholder("qmark", 0) == "?"
    assert placeholder("numeric", 0) == ":1"
    assert placeholder("numeric", 2) == ":3"
    assert placeholder("named", 1) == ":p2"

    with pytest.raises(ValueError):
        placeholder("format", 0)


def test_identifier_must_be_whitelisted():
    assert quote_identifier("name") == "`name`"

    with pytest.raises(ValueError):
        quote_identifier("password")

    with pytest.raises(ValueError):
        quote_identifier("name; DROP TABLE users; --")


def test_identifier_with_backtick_is_rejected():
    with pytest.raises(ValueError):
        quote_identifier("na`me")

    with pytest.raises(ValueError):
        quote_identifier("name`; DROP TABLE users; --")


def test_expand_in_uses_placeholders_not_joined_values():
    markers = expand_in(("alice", "bob", "carol"))

    assert markers == ("?", "?", "?")
    assert "alice" not in markers

    with pytest.raises(ValueError):
        expand_in(())


def test_limit_is_required_and_capped():
    with pytest.raises(ValueError):
        build_select("users", ["id"], None, None, None)

    with pytest.raises(ValueError):
        build_select("users", ["id"], None, None, 1001)

    plan = build_select("users", ["id"], None, None, 1000)

    assert plan["sql"] == "SELECT `id` FROM `users` LIMIT ?"
    assert plan["params"] == (1000,)


def test_insert_columns_and_params_stay_aligned():
    row = {"name": "alice", "status": "active"}

    plan = build_insert("users", row)

    assert plan["sql"] == (
        "INSERT INTO `users` (`name`, `status`) VALUES (?, ?)"
    )
    assert plan["params"] == ("alice", "active")
    assert plan["sql"].count("?") == len(plan["params"]) == len(row)

    with pytest.raises(ValueError):
        build_insert("users", {})


def test_policy_flags_allowed_string_concatenation():
    assert validate_policy(SAFE_POLICY) == []

    unsafe = dict(SAFE_POLICY)
    unsafe["allow_string_concat"] = True

    assert validate_policy(unsafe) == ["string_concat"]

    all_unsafe = {
        "allow_string_concat": True,
        "identifier_whitelist": False,
        "max_rows": None,
    }
    assert validate_policy(all_unsafe) == [
        "string_concat",
        "identifier_whitelist",
        "row_limit",
    ]


def test_batch_plans_do_not_share_params():
    plans = [
        {
            "table": "users",
            "columns": ["id"],
            "where": {"name": "alice"},
            "order": None,
            "limit": 10,
        },
        {
            "table": "users",
            "columns": ["id"],
            "where": {"name": "bob"},
            "order": None,
            "limit": 20,
        },
    ]

    batch = query_batch(plans, SAFE_POLICY)

    assert [plan["params"] for plan in batch["plans"]] == [
        ("alice", 10),
        ("bob", 20),
    ]
    assert batch["plans"][0]["params"] is not batch["plans"][1]["params"]


def test_order_direction_is_enum_validated():
    for bad_direction in ("DESC; DROP TABLE users; --", "desc", "", "ASC "):
        with pytest.raises(ValueError):
            build_select(
                "users",
                ["id"],
                None,
                ("created_at", bad_direction),
                10,
            )

    plan = build_select("users", ["id"], None, ("created_at", "ASC"), 10)

    assert "ORDER BY `created_at` ASC" in plan["sql"]
