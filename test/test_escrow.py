"""
Static safety checks on the escrow.

This contract holds real value, so the tests that matter are not about what
it computes but about the orderings and guards that stop money going
somewhere it should not. None of it can be executed here, since it needs
GenVM, so these read the source and assert its shape.

The rules being enforced:

  state is written before value moves, on every path
  a deal settles once and only once
  only the depositor can cancel, and only while nothing is decided
  cancelling is impossible once a verdict exists
  the only two destinations are the payee and the depositor
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESCROW = ROOT / "contracts" / "escrow.py"

EXPECTED_WRITE = {"open_deal", "resolve", "cancel"}
EXPECTED_VIEW = {
    "get_deal",
    "deal_ids",
    "count",
    "oracle",
    "minimum_verdict",
    "divergences",
}


def tree() -> ast.Module:
    return ast.parse(ESCROW.read_text(encoding="utf-8"))


def escrow_class() -> ast.ClassDef:
    for node in tree().body:
        if isinstance(node, ast.ClassDef) and node.name == "Escrow":
            return node
    raise AssertionError("no Escrow class")


def methods():
    out = {}
    for node in escrow_class().body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            name = ast.unparse(dec)
            if name.endswith("gl.public.view"):
                out[node.name] = ("view", node)
            elif "gl.public.write" in name:
                out[node.name] = ("write", node)
    return out


# --------------------------------------------------------------------
# surface
# --------------------------------------------------------------------

def test_surface_is_what_is_documented():
    m = methods()
    assert {n for n, (k, _) in m.items() if k == "view"} == EXPECTED_VIEW
    assert {n for n, (k, _) in m.items() if k == "write"} == EXPECTED_WRITE


def test_only_the_deposit_method_is_payable():
    """
    Any other payable method is a way for value to enter the contract
    without a deal recording who it belongs to, which would strand it.
    """
    payable = []
    for node in escrow_class().body:
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if ast.unparse(dec).endswith("payable"):
                    payable.append(node.name)
    assert payable == ["open_deal"]


def test_the_escrow_makes_no_judgements_of_its_own():
    """
    The verdict was settled under consensus elsewhere. This contract applies
    a threshold to it. A model or a web fetch appearing here would mean it
    had started re-deciding, and would make settling as slow and fragile as
    checking.
    """
    src = ESCROW.read_text(encoding="utf-8")
    for forbidden in (
        "gl.nondet",
        "run_nondet_unsafe",
        "eq_principle",
        "exec_prompt",
        "web.render",
    ):
        assert forbidden not in src, forbidden


# --------------------------------------------------------------------
# ordering: state before value
# --------------------------------------------------------------------

def _statement_index(fn: ast.FunctionDef, predicate) -> int:
    for i, node in enumerate(ast.walk(fn)):
        if predicate(node):
            return i
    return -1


def _first_line(fn: ast.FunctionDef, needle: str) -> int:
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.Expr, ast.Call)):
            text = ast.unparse(node)
            if needle in text:
                return node.lineno
    return -1


def test_state_is_written_before_value_moves():
    """
    The single most important property here. Marking the deal settled only
    after transferring would leave a window where the contract still thinks
    the deal is open.
    """
    m = methods()
    for name in ("resolve", "cancel"):
        fn = m[name][1]
        state_line = _first_line(fn, "deal.state =")
        store_line = _first_line(fn, "self.deals[key] = deal")
        transfer_line = _first_line(fn, "emit_transfer")
        assert state_line > 0, name
        assert store_line > 0, name
        assert transfer_line > 0, name
        assert state_line < transfer_line, f"{name}: state set after transfer"
        assert store_line < transfer_line, f"{name}: stored after transfer"


def test_every_settling_path_refuses_a_deal_that_is_not_open():
    m = methods()
    for name in ("resolve", "cancel"):
        body = ast.unparse(m[name][1])
        assert "!= STATE_OPEN" in body, f"{name} does not guard on state"


def test_value_can_only_reach_the_payee_or_the_depositor():
    """
    Enumerate every emit_transfer target in the file. Anything other than
    these two is a way for funds to leave to somewhere nobody agreed to.
    """
    targets = []
    for node in ast.walk(tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "emit_transfer":
                inner = node.func.value
                assert isinstance(inner, ast.Call), "unexpected transfer shape"
                targets.append(ast.unparse(inner.args[0]))
    assert targets, "no transfers found at all"
    allowed = {"recipient", "deal.depositor"}
    assert set(targets) <= allowed, f"unexpected transfer targets: {targets}"


def test_the_recipient_is_chosen_only_by_the_verdict():
    body = ast.unparse(methods()["resolve"][1])
    assert "recipient = deal.payee if release else deal.depositor" in body


# --------------------------------------------------------------------
# cancellation guards
# --------------------------------------------------------------------

def test_only_the_depositor_can_cancel():
    body = ast.unparse(methods()["cancel"][1])
    assert "only the depositor can cancel" in body
    assert "deal.depositor.as_hex.lower()" in body


def test_cancelling_is_impossible_once_the_claim_is_checked():
    """
    Otherwise a depositor watches the verdict and withdraws whenever it goes
    against them, which makes the escrow decorative.
    """
    body = ast.unparse(methods()["cancel"][1])
    assert "is_checked" in body
    assert "already been checked" in body


def test_the_cancellation_race_is_documented_not_hidden():
    """
    A depositor can still cancel between a check running and it being
    stored. That is a real limitation and the docstring says so rather than
    leaving someone to find it.
    """
    doc = ast.get_docstring(methods()["cancel"][1]) or ""
    assert "Known limitation" in doc
    assert "deadline" in doc


# --------------------------------------------------------------------
# deposit guards
# --------------------------------------------------------------------

def test_an_empty_deposit_is_refused():
    body = ast.unparse(methods()["open_deal"][1])
    assert "gl.message.value" in body
    assert "amount <= 0" in body


def test_payee_and_depositor_must_differ():
    """
    If they are the same account the verdict cannot change where the money
    ends up, so the deal proves nothing and only wastes fees.
    """
    body = ast.unparse(methods()["open_deal"][1])
    assert "payee and depositor are the same account" in body


def test_a_deal_id_cannot_be_reused():
    body = ast.unparse(methods()["open_deal"][1])
    assert "deal already exists" in body


# --------------------------------------------------------------------
# the argument
# --------------------------------------------------------------------

def test_verdict_strength_is_ordered_weakest_to_strongest():
    table = None
    for node in ast.walk(tree()):
        if isinstance(node, ast.Assign):
            if "_STRENGTH" in [ast.unparse(t) for t in node.targets]:
                table = ast.literal_eval(node.value)
    assert table == {
        "no_data": 0,
        "contested": 1,
        "majority": 2,
        "corroborated": 3,
    }
    assert list(table.values()) == sorted(table.values())


def test_divergences_counts_only_refunds_a_naive_oracle_would_have_paid():
    """
    The list that carries the whole argument. It must not quietly widen to
    include deals where nothing would have been paid anyway, because then it
    stops being evidence that dissent changed an outcome.
    """
    body = ast.unparse(methods()["divergences"][1])
    assert "STATE_REFUNDED" in body
    assert "naive_would_pay" in body


def test_the_contract_is_pure_ascii():
    raw = ESCROW.read_bytes()
    assert not [(i, b) for i, b in enumerate(raw) if b > 127 or b == 8]
