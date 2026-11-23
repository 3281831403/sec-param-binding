"""Contract stubs for the parameter-binding query builder.

Security model:

- Values are data. They travel only in ``params`` tuples and must never be
  interpolated into SQL text.
- Identifiers must be exact members of ``IDENTIFIER_WHITELIST`` and are quoted
  with backticks.
- Supported placeholder styles are qmark (``?``), numeric (``:1``, ``:2``,
  ...) and named (``:p1``, ``:p2``, ...).
- Every assertion against these contracts is exact; tolerance is 0.

All eight public functions are intentionally unimplemented and raise
``NotImplementedError``. The solver implements them in place without changing
the signatures or the tests.
"""

from collections.abc import Mapping

IDENTIFIER_WHITELIST = frozenset(
    {
        "users",
        "orders",
        "audit_log",
        "id",
        "name",
        "email",
        "status",
        "created_at",
        "user_id",
        "total",
        "note",
    }
)

MAX_ROWS = 1000

PLACEHOLDER_STYLES = ("qmark", "numeric", "named")

ORDER_DIRECTIONS = ("ASC", "DESC")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def placeholder(style: str, index: int) -> str:
    """Return the placeholder for ``style`` at zero-based ``index``.

    Supported styles:

    - ``qmark`` returns ``?`` for every index.
    - ``numeric`` returns ``:1``, ``:2`` and so on, using ``index + 1``.
    - ``named`` returns ``:p1``, ``:p2`` and so on, using ``index + 1``.

    The result depends only on the style and the position. A query value must
    never be supplied here or formatted into the returned text. Unknown
    styles, negative indexes and non-integer indexes raise ``ValueError``.
    Comparison is exact, tolerance 0.
    """
    if style not in PLACEHOLDER_STYLES:
        raise ValueError(f"unknown placeholder style: {style!r}")
    if not _is_int(index) or index < 0:
        raise ValueError(f"invalid placeholder index: {index!r}")
    if style == "qmark":
        return "?"
    if style == "numeric":
        return f":{index + 1}"
    return f":p{index + 1}"


def bind_values(values, style: str) -> tuple:
    """Return ``values`` as one isolated bind-parameter tuple for ``style``.

    The returned tuple preserves value order and values exactly. No value is
    rendered into SQL or into placeholder text, and no value is converted to a
    SQL literal. ``style`` must be one of ``PLACEHOLDER_STYLES``. A bare string
    is rejected because it is a single value, not a collection of parameters.
    An empty iterable yields an empty tuple. Comparison is exact, tolerance 0.
    """
    if style not in PLACEHOLDER_STYLES:
        raise ValueError(f"unknown placeholder style: {style!r}")
    if isinstance(values, (str, bytes)):
        raise ValueError("a bare string is a single value, not parameters")
    return tuple(values)


def quote_identifier(name: str) -> str:
    """Validate ``name`` against ``IDENTIFIER_WHITELIST`` and quote it.

    Allowed names are returned wrapped in backticks; for example, a column
    named name is returned surrounded by backticks. Membership is exact. Table
    and column names outside ``IDENTIFIER_WHITELIST`` raise ``ValueError``.
    Names containing a backtick, semicolon, quote, whitespace or comment marker
    are outside the whitelist and must be rejected, so an unescaped internal
    backtick can never be emitted. Comparison is exact, tolerance 0.
    """
    if not isinstance(name, str) or name not in IDENTIFIER_WHITELIST:
        raise ValueError(f"identifier not whitelisted: {name!r}")
    return f"`{name}`"


def build_select(table: str, columns, where, order, limit) -> dict:
    """Build a SELECT plan as a mapping with ``sql`` and ``params``.

    ``table`` and every column must pass ``quote_identifier``. ``columns`` must
    be a non-empty sequence. ``where`` is ``None`` or a mapping of allowed
    column names to scalar values; each condition becomes ``column = ?`` and
    conditions are joined with ``AND`` in insertion order. ``order`` is
    ``None`` or a two-item tuple of an allowed column and a direction; the
    direction must be exactly ``ASC`` or ``DESC``. ``limit`` is required and
    must be an integer from 1 through ``MAX_ROWS`` inclusive; it is appended to
    ``params`` and rendered as ``LIMIT ?``.

    Return ``{"sql": <statement>, "params": <tuple>}``. SQL uses qmark
    placeholders, has no trailing semicolon and contains no bound values.
    Invalid inputs raise ``ValueError``. Comparison is exact, tolerance 0.
    """
    if not _is_int(limit) or not 1 <= limit <= MAX_ROWS:
        raise ValueError(f"limit must be an integer from 1 to {MAX_ROWS}")

    if isinstance(columns, (str, bytes)) or not columns:
        raise ValueError("columns must be a non-empty sequence")
    quoted_columns = [quote_identifier(column) for column in columns]

    sql = f"SELECT {', '.join(quoted_columns)} FROM {quote_identifier(table)}"
    params = []

    if where is not None:
        if not isinstance(where, Mapping):
            raise ValueError("where must be a mapping of column to value")
        conditions = []
        for column, value in where.items():
            conditions.append(f"{quote_identifier(column)} = ?")
            params.append(value)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

    if order is not None:
        if not isinstance(order, (tuple, list)) or len(order) != 2:
            raise ValueError("order must be a (column, direction) pair")
        order_column, direction = order
        if direction not in ORDER_DIRECTIONS:
            raise ValueError(f"invalid order direction: {direction!r}")
        sql += f" ORDER BY {quote_identifier(order_column)} {direction}"

    sql += " LIMIT ?"
    params.append(limit)

    return {"sql": sql, "params": tuple(params)}


def build_insert(table: str, row) -> dict:
    """Build an INSERT plan as a mapping with ``sql`` and ``params``.

    ``table`` and every key of ``row`` must pass ``quote_identifier``. ``row``
    must be a non-empty mapping. Columns follow the row insertion order and one
    qmark is emitted for each key, so column count, placeholder count and
    ``params`` length are always equal and aligned. No value is interpolated
    into SQL. Empty rows, non-mappings and unknown columns raise ``ValueError``.

    Return ``{"sql": <statement>, "params": <tuple>}``. Comparison is exact,
    tolerance 0.
    """
    if not isinstance(row, Mapping) or not row:
        raise ValueError("row must be a non-empty mapping")

    quoted_columns = [quote_identifier(column) for column in row]
    marks = ", ".join("?" for _ in row)
    sql = (
        f"INSERT INTO {quote_identifier(table)} "
        f"({', '.join(quoted_columns)}) VALUES ({marks})"
    )
    return {"sql": sql, "params": tuple(row.values())}


def expand_in(values) -> tuple:
    """Expand a collection into one qmark placeholder per item.

    The result is a tuple such as ``("?", "?", "?")``, never a comma-joined
    list of values. Input order is preserved and the values themselves never
    appear in the result. Empty input and a bare string raise ``ValueError``.
    Comparison is exact, tolerance 0.
    """
    if isinstance(values, (str, bytes)):
        raise ValueError("a bare string is a single value, not a collection")
    items = tuple(values)
    if not items:
        raise ValueError("cannot expand an empty collection")
    return tuple("?" for _ in items)


def validate_policy(policy) -> list[str]:
    """Return stable issue codes for an unsafe binding policy.

    ``policy`` is a mapping with these keys:

    - ``allow_string_concat``: ``True`` means string concatenation is allowed.
    - ``identifier_whitelist``: ``False`` means identifiers are not checked.
    - ``max_rows``: ``None``, a non-integer, a value below 1 or a value above
      ``MAX_ROWS`` means no useful row cap.

    Return codes in this fixed order: ``string_concat``, then
    ``identifier_whitelist``, then ``row_limit``. A safe policy returns ``[]``.
    Missing keys are unsafe. Comparison is exact, tolerance 0.
    """
    issues = []
    if not isinstance(policy, Mapping):
        return ["string_concat", "identifier_whitelist", "row_limit"]

    if policy.get("allow_string_concat", True):
        issues.append("string_concat")
    if not policy.get("identifier_whitelist", False):
        issues.append("identifier_whitelist")

    max_rows = policy.get("max_rows")
    if not _is_int(max_rows) or not 1 <= max_rows <= MAX_ROWS:
        issues.append("row_limit")

    return issues


def query_batch(plans, policy) -> dict:
    """Build multiple SELECT plans independently.

    ``plans`` is a sequence of mappings with the keys accepted by
    ``build_select``: ``table``, ``columns``, ``where``, ``order`` and
    ``limit``. ``policy`` is checked with ``validate_policy``; any issue raises
    ``ValueError`` before a plan is built.

    Each plan receives its own fresh params tuple and must equal the plan
    produced by a separate ``build_select`` call. With a safe policy return
    ``{"plans": [plan, ...], "issues": []}``. An empty sequence returns an empty
    plans list. Comparison is exact, tolerance 0.
    """
    issues = validate_policy(policy)
    if issues:
        raise ValueError(f"unsafe binding policy: {', '.join(issues)}")

    built = []
    for spec in plans:
        plan = build_select(
            spec["table"],
            spec["columns"],
            spec.get("where"),
            spec.get("order"),
            spec["limit"],
        )
        built.append(plan)

    return {"plans": built, "issues": []}
