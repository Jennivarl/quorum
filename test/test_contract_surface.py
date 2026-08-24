"""
Static checks on the contract itself.

The contract cannot be exercised here, because its interesting methods need
GenVM. What can be checked without a chain is its shape, and the two ways
that shape has historically gone wrong: a view method quietly writing, and
the deployed bundle drifting away from the sources it was generated from.

Both failures are invisible until they are expensive. A view that writes is
rejected at deploy time with a message that does not name the method. A
stale bundle deploys perfectly and runs code nobody has read.
"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contracts" / "quorum.py"
BUNDLE = ROOT / "contracts" / "quorum_bundle.py"

EXPECTED_WRITE = {"check"}
EXPECTED_VIEW = {
    "get_check",
    "verdict_of",
    "is_checked",
    "check_ids",
    "count",
    "summaries",
}


def contract_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Quorum":
            return node
    raise AssertionError("no Quorum class")


def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def decorator_name(dec: ast.expr) -> str:
    return ast.unparse(dec)


def public_methods(cls: ast.ClassDef):
    out = {}
    for node in cls.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            name = decorator_name(dec)
            if name.endswith("gl.public.view"):
                out[node.name] = ("view", node)
            elif name.endswith("gl.public.write"):
                out[node.name] = ("write", node)
    return out


# --------------------------------------------------------------------
# surface
# --------------------------------------------------------------------

def test_public_surface_is_exactly_what_is_documented():
    methods = public_methods(contract_class(parsed(CONTRACT)))
    views = {n for n, (kind, _) in methods.items() if kind == "view"}
    writes = {n for n, (kind, _) in methods.items() if kind == "write"}
    assert views == EXPECTED_VIEW
    assert writes == EXPECTED_WRITE


def test_only_one_method_can_cost_anything():
    """
    Every added write is a new way for a caller to spend money and a new
    surface for a stuck transaction. One is the intended number.
    """
    methods = public_methods(contract_class(parsed(CONTRACT)))
    writes = [n for n, (kind, _) in methods.items() if kind == "write"]
    assert writes == ["check"]


def test_no_view_method_writes_storage():
    """
    A view that mutates state is rejected at deploy time, and the error does
    not say which method did it. Catching it here names the method.
    """
    offenders = []
    for name, (kind, node) in public_methods(contract_class(parsed(CONTRACT))).items():
        if kind != "view":
            continue
        for sub in ast.walk(node):
            targets = []
            if isinstance(sub, ast.Assign):
                targets = sub.targets
            elif isinstance(sub, (ast.AugAssign, ast.AnnAssign)):
                targets = [sub.target]
            for t in targets:
                text = ast.unparse(t)
                if text.startswith("self."):
                    offenders.append((name, text))
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                call = ast.unparse(sub.func)
                if call.startswith("self.") and sub.func.attr in {
                    "append",
                    "pop",
                    "clear",
                    "extend",
                }:
                    offenders.append((name, call))
    assert not offenders, f"view methods writing storage: {offenders}"


def test_the_index_is_appended_wherever_a_record_is_stored():
    """
    `checks` and `ids` have to stay in step. A record written without its id
    appended is invisible to the archive and to `count`, and nothing errors.
    """
    src = CONTRACT.read_text(encoding="utf-8")
    stores = src.count("self.checks[key] = record")
    appends = src.count("self.ids.append(key)")
    assert stores == 1, f"expected one store, found {stores}"
    assert appends == stores


def test_summaries_does_not_return_quotes():
    """
    The index exists to avoid shipping every quote to render a list. If the
    quotes creep back in, it has stopped being worth having.
    """
    node = public_methods(contract_class(parsed(CONTRACT)))["summaries"][1]
    # Skip the docstring: it is allowed to mention the very fields the code
    # must not return, and matching against it tests the prose instead.
    statements = node.body[1:] if ast.get_docstring(node) else node.body
    body = "\n".join(ast.unparse(s) for s in statements)
    assert "quote" not in body
    assert "answers" not in body


# --------------------------------------------------------------------
# the bundle
# --------------------------------------------------------------------

def test_bundle_is_current():
    """
    Regenerate into a temp copy and compare. The bundle is what deploys, so
    a stale one means the audited source and the running code differ.
    """
    before = BUNDLE.read_text(encoding="utf-8")
    subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "build_bundle.py")],
        check=True,
        capture_output=True,
        cwd=ROOT,
    )
    after = BUNDLE.read_text(encoding="utf-8")
    assert before == after, "bundle is stale; run python deploy/build_bundle.py"


def test_bundle_exposes_the_same_surface_as_the_source():
    assert public_methods(contract_class(parsed(BUNDLE))).keys() == public_methods(
        contract_class(parsed(CONTRACT))
    ).keys()


def test_bundle_has_no_local_imports_left():
    """
    GenVM deploys one file with no sibling modules, so any surviving local
    import is an ImportError at deploy time.
    """
    for node in ast.walk(parsed(BUNDLE)):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("contracts"), node.module


def test_bundle_is_pure_ascii():
    """
    A stray smart quote or dash in the deployed source has cost a deployment
    before. Bytes, not characters, because that is what the runtime sees.
    """
    raw = BUNDLE.read_bytes()
    bad = [(i, b) for i, b in enumerate(raw) if b > 127 or b == 8]
    assert not bad, f"non-ascii or control bytes at {bad[:5]}"


def test_bundle_declares_the_pinned_runtime():
    first = BUNDLE.read_text(encoding="utf-8").split("\n", 1)[0]
    assert first.strip().startswith('# { "Depends": "py-genlayer:')


def test_bundle_imports_no_forbidden_modules():
    """
    `random` and `time` are nondeterministic and have no place here. This
    caught a bundler that was injecting `import random` into every build
    regardless of what the sources actually used.
    """
    forbidden = {"random", "time", "datetime", "os", "secrets", "uuid"}
    found = set()
    for node in ast.walk(parsed(BUNDLE)):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    assert not (found & forbidden), f"forbidden imports: {found & forbidden}"


# --------------------------------------------------------------------
# the reference consumer
# --------------------------------------------------------------------

SETTLE = ROOT / "contracts" / "settle.py"

SETTLE_WRITE = {"settle"}
SETTLE_VIEW = {
    "get_settlement",
    "settlement_ids",
    "count",
    "oracle",
    "minimum_verdict",
    "divergences",
}


def settle_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settle":
            return node
    raise AssertionError("no Settle class")


def test_the_consumer_has_the_surface_it_documents():
    methods = public_methods(settle_class(parsed(SETTLE)))
    assert {n for n, (k, _) in methods.items() if k == "view"} == SETTLE_VIEW
    assert {n for n, (k, _) in methods.items() if k == "write"} == SETTLE_WRITE


def test_the_consumer_needs_no_nondeterminism():
    """
    The judgement already happened in Quorum under consensus. A consumer
    reading a stored verdict should be exact and cheap: no model, no web
    access, no equivalence principle. If any of that appears here, the
    consumer has started re-deciding what the oracle already decided.
    """
    src = SETTLE.read_text(encoding="utf-8")
    for forbidden in (
        "gl.nondet",
        "run_nondet_unsafe",
        "eq_principle",
        "exec_prompt",
        "web.render",
    ):
        assert forbidden not in src, forbidden


def test_verdict_strength_is_ordered_weakest_to_strongest():
    """
    The whole refusal rule is a comparison against this table, so an
    ordering mistake would silently settle on contested figures.
    """
    tree = parsed(SETTLE)
    table = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [ast.unparse(t) for t in node.targets]
            if "_STRENGTH" in targets:
                table = ast.literal_eval(node.value)
    assert table is not None, "no _STRENGTH table"
    assert table == {
        "no_data": 0,
        "contested": 1,
        "majority": 2,
        "corroborated": 3,
    }
    assert list(table.values()) == sorted(table.values())


def test_a_refused_settlement_stores_no_value():
    """
    Refusing and then storing the figure anyway would leave the exact
    number a caller must not act on sitting in the record as though it had
    been accepted.
    """
    src = SETTLE.read_text(encoding="utf-8")
    assert 'value=value if settled else ""' in src


def test_the_counterfactual_is_recorded():
    """
    The argument for the whole project is the case where dissent changed
    the decision. If the naive comparison stops being stored, that argument
    stops being demonstrable.
    """
    src = SETTLE.read_text(encoding="utf-8")
    assert "naive_value" in src
    assert "naive_would_settle" in src
    methods = public_methods(settle_class(parsed(SETTLE)))
    assert "divergences" in methods


def test_the_consumer_is_pure_ascii():
    raw = SETTLE.read_bytes()
    assert not [(i, b) for i, b in enumerate(raw) if b > 127 or b == 8]
