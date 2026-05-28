# Code style and refactoring patterns

## General

- Tests are run with `uv run --with pytest python -m pytest`
- One commit per agreed change, after all files are edited and tests pass

## Refactoring patterns

These patterns were established through deliberate refactoring of the codebase.
Apply them when writing new code or spotting violations.

### Move logic onto the class that owns the data

If a function or closure mostly reads fields from one class, it belongs as a
method on that class. Examples: `FilterSpec.matches()`,
`FilterSpec.matches_comment()`, `ReportSpec.show_time_cols()`,
`ColumnDisplay.cell()`, `ColumnDisplay.comment_cell()`,
`GithubData.make_ctx()`.

Closures that capture a data-class's fields to compute something about that
object are a sign the logic has wandered away from the data.

### No inner closures for per-row/per-item logic

If a closure closes over an object's fields to compute something about that
object, make it a method instead. All such closures in `_report_data_lines`
have been eliminated by this rule.

### ABC + concrete frozen dataclasses for spec/filter hierarchies

Use `class Foo(ABC)` with `@abstractmethod` for the interface, and `@dataclass`
subclasses for concrete variants. See `FilterSpec` → `ColumnFilterSpec` /
`ComparisonFilterSpec`. Avoids `isinstance` chains scattered through callers.

### Replace free helper functions wrapping a class with methods

If a free function's first argument is always an instance of one class, make it
a method on that class. Example: `cell(col, ctx, show_time)` →
`col.cell(ctx, show_time)`.

### Extract value objects for rich return types

When a return type needs downstream logic, give it a class. Example: `Report`
instead of `list[list[str]]`, carrying `aggregate()`, `widths()`, and
`render()` as methods so each step is independently testable.

### Deduplicate shared utilities into `_util.py`

Low-level utilities shared across modules (sort helpers, ANSI stripping, etc.)
belong in `_util.py`. Example: `_Rev` was copy-pasted in `report.py` and
`timely_report.py`; it now lives in `_util.py`.

### Lazy imports inside method bodies for cross-module dependencies

When adding a method to class A that needs a type from module B, but B already
imports A (creating a cycle), import B lazily inside the method body. Use
`TYPE_CHECKING` for annotations only. Examples: `GithubData.make_ctx` importing
`PRContext`; `ColumnFilterSpec.matches_comment` importing `COMMENT_TIME_COL`.

### Module-local dataclasses for column sets outside `columns.py`

Never construct `Column(...)` outside `columns.py`. `Column.__post_init__`
registers every instance in the global `Column._registry`, so a foreign module
creating `Column` objects with colliding names silently overwrites the PR report
columns and breaks their `cell=` functions.

Any module defining its own column set must use a local frozen dataclass (e.g.
`_TCol` in `timely_report.py`) with no `__post_init__` registration.
