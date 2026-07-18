"""
Full test suite for logic.py -- the pure business logic (no DB, no HTTP).

Run with:
    pytest test_logic.py -v

These tests matter because logic.py is where money-math bugs actually live.
Anyone can split an even amount; the tests below specifically hunt for
rounding bugs, lost/duplicated units, and correctness of the debt-simplification
algorithm -- the exact things that are easy to get subtly wrong.
"""

import pytest
from logic import (
    split_equal,
    split_exact,
    split_percentage,
    split_shares,
    compute_balances,
    simplify_debts,
)


# ---------------------------------------------------------------------------
# split_equal
# ---------------------------------------------------------------------------

def test_equal_split_evenly_divisible():
    result = split_equal(300, [1, 2, 3])
    assert result == {1: 100, 2: 100, 3: 100}
    assert sum(result.values()) == 300


def test_equal_split_not_evenly_divisible_no_unit_lost():
    result = split_equal(100, [1, 2, 3])
    assert sum(result.values()) == 100
    assert max(result.values()) - min(result.values()) <= 1
    assert set(result.keys()) == {1, 2, 3}


def test_equal_split_awkward_prime_division():
    user_ids = list(range(7))
    result = split_equal(100, user_ids)
    assert sum(result.values()) == 100
    assert max(result.values()) - min(result.values()) <= 1


def test_equal_split_single_user_gets_everything():
    result = split_equal(500, [1])
    assert result == {1: 500}


def test_equal_split_large_amount_many_users():
    user_ids = list(range(37))
    result = split_equal(999983, user_ids)
    assert sum(result.values()) == 999983


# ---------------------------------------------------------------------------
# split_exact
# ---------------------------------------------------------------------------

def test_exact_split_valid_sum_passes_through():
    result = split_exact(300, {1: 100, 2: 200})
    assert result == {1: 100, 2: 200}


def test_exact_split_invalid_sum_raises():
    with pytest.raises(ValueError):
        split_exact(300, {1: 100, 2: 150})


def test_exact_split_zero_for_one_user_is_allowed():
    result = split_exact(100, {1: 100, 2: 0})
    assert result == {1: 100, 2: 0}


# ---------------------------------------------------------------------------
# split_percentage
# ---------------------------------------------------------------------------

def test_percentage_split_even():
    result = split_percentage(1000, {1: 50, 2: 50})
    assert result == {1: 500, 2: 500}


def test_percentage_split_rounding_no_unit_lost():
    result = split_percentage(100, {1: 33, 2: 33, 3: 34})
    assert sum(result.values()) == 100


def test_percentage_split_must_sum_to_100():
    with pytest.raises(ValueError):
        split_percentage(1000, {1: 40, 2: 40})


def test_percentage_split_uneven_weights_no_unit_lost():
    result = split_percentage(1001, {1: 50, 2: 30, 3: 20})
    assert sum(result.values()) == 1001


# ---------------------------------------------------------------------------
# split_shares
# ---------------------------------------------------------------------------

def test_shares_split_basic_ratio():
    result = split_shares(300, {"alice": 2, "bob": 1})
    assert result == {"alice": 200, "bob": 100}


def test_shares_split_equal_shares_behaves_like_equal_split():
    result = split_shares(100, {1: 1, 2: 1, 3: 1})
    assert sum(result.values()) == 100
    assert max(result.values()) - min(result.values()) <= 1


def test_shares_split_no_unit_lost_on_awkward_total():
    result = split_shares(1000, {1: 3, 2: 5, 3: 2})
    assert sum(result.values()) == 1000
    assert result[2] > result[1] > result[3]


# ---------------------------------------------------------------------------
# compute_balances
# ---------------------------------------------------------------------------

class FakePayer:
    def __init__(self, user_id, amount_paid):
        self.user_id = user_id
        self.amount_paid = amount_paid

class FakeSplit:
    def __init__(self, user_id, amount_owed):
        self.user_id = user_id
        self.amount_owed = amount_owed

class FakeExpense:
    def __init__(self, payers, splits):
        self.payers = payers
        self.splits = splits

class FakeSettlement:
    def __init__(self, paid_by, paid_to, amount):
        self.paid_by = paid_by
        self.paid_to = paid_to
        self.amount = amount


def test_compute_balances_single_expense_equal_split():
    expense = FakeExpense(
        payers=[FakePayer(1, 1000)],
        splits=[FakeSplit(1, 500), FakeSplit(2, 500)],
    )
    balances = compute_balances([expense], [])
    assert balances[1] == 500
    assert balances[2] == -500
    assert sum(balances.values()) == 0


def test_compute_balances_multiple_expenses_accumulate():
    expense1 = FakeExpense(payers=[FakePayer(1, 1000)], splits=[FakeSplit(1, 500), FakeSplit(2, 500)])
    expense2 = FakeExpense(payers=[FakePayer(2, 600)], splits=[FakeSplit(1, 300), FakeSplit(2, 300)])
    balances = compute_balances([expense1, expense2], [])
    assert balances[1] == 200
    assert balances[2] == -200
    assert sum(balances.values()) == 0


def test_compute_balances_settlement_reduces_debt():
    expense = FakeExpense(payers=[FakePayer(1, 1000)], splits=[FakeSplit(1, 500), FakeSplit(2, 500)])
    settlement = FakeSettlement(paid_by=2, paid_to=1, amount=500)
    balances = compute_balances([expense], [settlement])
    assert balances[1] == 0
    assert balances[2] == 0


def test_compute_balances_multi_payer_expense():
    expense = FakeExpense(
        payers=[FakePayer(1, 1500), FakePayer(2, 1500)],
        splits=[FakeSplit(1, 1000), FakeSplit(2, 1000), FakeSplit(3, 1000)],
    )
    balances = compute_balances([expense], [])
    assert balances[1] == 500
    assert balances[2] == 500
    assert balances[3] == -1000
    assert sum(balances.values()) == 0


# ---------------------------------------------------------------------------
# simplify_debts
# ---------------------------------------------------------------------------

def test_simplify_debts_two_person_case():
    balances = {1: 500, 2: -500}
    result = simplify_debts(balances)
    assert result == [{"from_user": 2, "to_user": 1, "amount": 500}]


def test_simplify_debts_three_person_case_minimum_transactions():
    balances = {1: 1500, 2: -900, 3: -600}
    result = simplify_debts(balances)
    assert len(result) == 2

    final = dict(balances)
    for txn in result:
        final[txn["from_user"]] += txn["amount"]
        final[txn["to_user"]] -= txn["amount"]
    assert all(v == 0 for v in final.values())


def test_simplify_debts_already_settled_returns_nothing():
    balances = {1: 0, 2: 0, 3: 0}
    result = simplify_debts(balances)
    assert result == []


def test_simplify_debts_five_person_case_never_worse_than_naive():
    balances = {1: 1000, 2: 500, 3: -300, 4: -700, 5: -500}
    result = simplify_debts(balances)

    final = dict(balances)
    for txn in result:
        final[txn["from_user"]] += txn["amount"]
        final[txn["to_user"]] -= txn["amount"]
    assert all(v == 0 for v in final.values())
    assert len(result) <= len(balances) - 1


def test_simplify_debts_transaction_amounts_are_positive():
    balances = {1: 300, 2: 200, 3: -500}
    result = simplify_debts(balances)
    assert all(txn["amount"] > 0 for txn in result)
