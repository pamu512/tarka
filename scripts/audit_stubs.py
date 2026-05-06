#!/usr/bin/env python3
"""Tier-1 Honesty gate: AST scan of services/ for API stubs and empty implementations.

Fails (exit 1) on:
  - A function, async function, or lambda returning a dict literal containing the
    constant key ``status`` mapped to the constant value ``stub`` (AST only — no
    textual grep, so ``stub`` in comments or identifiers does not match).
  - ``raise NotImplementedError`` (including qualified ``builtins.NotImplementedError``)
    in a concrete (non-``@abstractmethod`` / non-``@overload``) function body.
  - A function whose body (after stripping a leading docstring) consists only of
    ``pass`` and/or standalone ``...`` (Ellipsis) — classic no-op stubs.
    Methods on classes that inherit ``typing.Protocol`` / ``Protocol`` skip this
    empty-body rule (Protocol interface surface uses ``...``).

``@abstractmethod`` / ``@abstractclassmethod`` / ``@abstractstaticmethod`` and
``@typing.overload`` are excluded from the NotImplemented, stub-dict, and empty-body
rules on *that* function.

Class-level ``pass`` is not treated as a function stub.

Uses the stdlib ``ast`` module only.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Violation:
    path: Path
    lineno: int
    message: str


def _services_root(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1]).resolve()
    return (Path(__file__).resolve().parent.parent / "services").resolve()


def _repo_root(services_root: Path) -> Path:
    return services_root.parent


def _format_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_py_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        parts = path.parts
        if "__pycache__" in parts:
            continue
        if any(p in (".venv", "venv", ".eggs", "node_modules") for p in parts):
            continue
        if "tests" in parts:
            continue
        rel = str(path.relative_to(root))
        if rel.startswith("test_") or rel.endswith("_test.py"):
            continue
        yield path


def _strip_leading_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _is_stub_status_dict(node: ast.expr) -> bool:
    if not isinstance(node, ast.Dict):
        return False
    for key, val in zip(node.keys, node.values, strict=False):
        if key is None:
            continue
        if not (isinstance(key, ast.Constant) and key.value == "status"):
            continue
        if isinstance(val, ast.Constant) and val.value == "stub":
            return True
    return False


def _expr_contains_stub_dict(node: ast.expr) -> bool:
    if _is_stub_status_dict(node):
        return True
    if isinstance(node, ast.Lambda):
        return bool(node.body and _expr_contains_stub_dict(node.body))
    if isinstance(node, ast.IfExp):
        return _expr_contains_stub_dict(node.body) or _expr_contains_stub_dict(node.orelse)
    if isinstance(node, ast.BoolOp):
        return any(_expr_contains_stub_dict(v) for v in node.values)
    if isinstance(node, ast.NamedExpr):
        return _expr_contains_stub_dict(node.value)
    return False


def _decorator_names(decs: list[ast.expr]) -> set[str]:
    names: set[str] = set()
    for d in decs:
        if isinstance(d, ast.Name):
            names.add(d.id)
        elif isinstance(d, ast.Attribute):
            names.add(d.attr)
        elif isinstance(d, ast.Call):
            f = d.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def _skip_function_for_abstract_rules(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    decs = _decorator_names(node.decorator_list)
    return (
        bool(decs & {"abstractmethod", "abstractclassmethod", "abstractstaticmethod"})
        or "overload" in decs
    )


def _class_has_protocol_base(class_node: ast.ClassDef) -> bool:
    for base in class_node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _is_ellipsis_expr(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is Ellipsis


def _stmt_is_pass_or_ellipsis(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    return bool(isinstance(stmt, ast.Expr) and _is_ellipsis_expr(stmt.value))


def _function_body_is_empty_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if _skip_function_for_abstract_rules(node):
        return False
    body = _strip_leading_docstring(list(node.body))
    if not body:
        return False
    return all(_stmt_is_pass_or_ellipsis(s) for s in body)


def _is_raise_notimplemented_exc(exc: ast.expr | None) -> bool:
    if exc is None:
        return False
    if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
        return True
    if isinstance(exc, ast.Call):
        f = exc.func
        if isinstance(f, ast.Name) and f.id == "NotImplementedError":
            return True
        if isinstance(f, ast.Attribute) and f.attr == "NotImplementedError":
            return True
    return False


def _scan_raise_notimplemented(
    node: ast.AST,
    violations: list[Violation],
    path: Path,
    repo_root: Path,
    qualname: str,
    skip: bool,
) -> None:
    if skip:
        return
    if isinstance(node, ast.Raise) and _is_raise_notimplemented_exc(node.exc):
        violations.append(
            Violation(
                path,
                getattr(node, "lineno", 0) or 0,
                f"{_format_path(path, repo_root)}:{getattr(node, 'lineno', 0) or 0}: "
                f"{qualname}: raise NotImplementedError",
            )
        )
        return
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        _scan_raise_notimplemented(child, violations, path, repo_root, qualname, skip)


def _scan_return_stub_dict(
    node: ast.AST, violations: list[Violation], path: Path, repo_root: Path, qualname: str
) -> None:
    if isinstance(node, ast.Assign) and node.value and _expr_contains_stub_dict(node.value):
        ln = getattr(node, "lineno", 0) or 0
        violations.append(
            Violation(
                path,
                ln,
                f"{_format_path(path, repo_root)}:{ln}: "
                f"{qualname}: assignment value includes dict literal with status='stub'",
            )
        )
    elif isinstance(node, ast.AnnAssign) and node.value and _expr_contains_stub_dict(node.value):
        ln = getattr(node, "lineno", 0) or 0
        violations.append(
            Violation(
                path,
                ln,
                f"{_format_path(path, repo_root)}:{ln}: "
                f"{qualname}: annotated assignment value includes dict literal with status='stub'",
            )
        )
    elif (
        isinstance(node, ast.Return)
        and node.value is not None
        and _expr_contains_stub_dict(node.value)
    ):
        ln = getattr(node, "lineno", 0) or 0
        violations.append(
            Violation(
                path,
                ln,
                f"{_format_path(path, repo_root)}:{ln}: "
                f"{qualname}: return dict literal includes status='stub'",
            )
        )
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        _scan_return_stub_dict(child, violations, path, repo_root, qualname)


def _empty_stub_violation_message(
    path: Path, repo_root: Path, lineno: int, qualname: str, kind: str
) -> str:
    rel = _format_path(path, repo_root)
    return f"{rel}:{lineno}: {qualname}: function body is only {kind} (no implementation)"


def _scan_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    violations: list[Violation],
    path: Path,
    repo_root: Path,
    outer: str,
    class_protocol: bool,
) -> None:
    name = f"{outer}.{node.name}" if outer else node.name
    skip = _skip_function_for_abstract_rules(node)
    if not class_protocol and _function_body_is_empty_stub(node):
        violations.append(
            Violation(
                path,
                getattr(node, "lineno", 0) or 0,
                _empty_stub_violation_message(
                    path,
                    repo_root,
                    getattr(node, "lineno", 0) or 0,
                    name,
                    "'pass' and/or '...'",
                ),
            )
        )
    for stmt in node.body:
        _scan_raise_notimplemented(stmt, violations, path, repo_root, name, skip)
    if not skip:
        for stmt in node.body:
            _scan_return_stub_dict(stmt, violations, path, repo_root, name)
    for child in node.body:
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            _scan_function(child, violations, path, repo_root, name, class_protocol=False)
        elif isinstance(child, ast.ClassDef):
            _scan_class(child, violations, path, repo_root, name)


def _scan_class(
    node: ast.ClassDef, violations: list[Violation], path: Path, repo_root: Path, outer: str
) -> None:
    name = f"{outer}.{node.name}" if outer else node.name
    is_protocol = _class_has_protocol_base(node)
    for child in node.body:
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            _scan_function(child, violations, path, repo_root, name, class_protocol=is_protocol)
        elif isinstance(child, ast.ClassDef):
            _scan_class(child, violations, path, repo_root, name)


def _scan_module(
    tree: ast.Module, violations: list[Violation], path: Path, repo_root: Path
) -> None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            _scan_function(node, violations, path, repo_root, "", class_protocol=False)
        elif isinstance(node, ast.ClassDef):
            _scan_class(node, violations, path, repo_root, "")


def _scan_module_level_lambda_assignments(
    tree: ast.Module, violations: list[Violation], path: Path, repo_root: Path
) -> None:
    """Catch ``f = lambda: {"status": "stub"}`` at module level."""

    class V(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign) -> None:
            if node.value and isinstance(node.value, ast.Lambda):
                lam = node.value
                if lam.body and _expr_contains_stub_dict(lam.body):
                    ln = getattr(node, "lineno", 0) or 0
                    violations.append(
                        Violation(
                            path,
                            ln,
                            f"{_format_path(path, repo_root)}:{ln}: "
                            "module-level assignment: lambda returns dict literal including status='stub'",
                        )
                    )
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if node.value and isinstance(node.value, ast.Lambda):
                lam = node.value
                if lam.body and _expr_contains_stub_dict(lam.body):
                    ln = getattr(node, "lineno", 0) or 0
                    violations.append(
                        Violation(
                            path,
                            ln,
                            f"{_format_path(path, repo_root)}:{ln}: "
                            "module-level annotated assignment: lambda returns dict literal including status='stub'",
                        )
                    )
            self.generic_visit(node)

    V().visit(tree)


def audit(root: Path) -> list[Violation]:
    repo_root = _repo_root(root)
    violations: list[Violation] = []
    for path in _iter_py_files(root):
        try:
            src = path.read_text(encoding="utf-8")
        except OSError as e:
            violations.append(
                Violation(
                    path,
                    0,
                    f"{_format_path(path, repo_root)}:0: could not read file: {e}",
                )
            )
            continue
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError as e:
            ln = e.lineno or 0
            violations.append(
                Violation(
                    path,
                    ln,
                    f"{_format_path(path, repo_root)}:{ln}: syntax error: {e.msg}",
                )
            )
            continue
        ast.fix_missing_locations(tree)
        _scan_module(tree, violations, path, repo_root)
        _scan_module_level_lambda_assignments(tree, violations, path, repo_root)
    return violations


def main(argv: list[str]) -> int:
    root = _services_root(argv)
    repo_root = _repo_root(root)
    if not root.is_dir():
        print(f"audit_stubs: services root is not a directory: {root}", file=sys.stderr)
        return 1
    violations = audit(root)
    if not violations:
        print(
            f"audit_stubs: OK (AST-scanned Python under {root.relative_to(repo_root).as_posix()}/)"
        )
        return 0
    for v in sorted(violations, key=lambda x: (str(x.path), x.lineno, x.message)):
        # message already includes repo-relative path:line for primary findings
        print(v.message)
    print(f"\naudit_stubs: FAILED with {len(violations)} violation(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
