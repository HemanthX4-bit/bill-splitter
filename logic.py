"""
Pure business logic -- no database, no HTTP. This is deliberate: these
functions take plain Python data in and return plain Python data out,
so they're trivial to unit test in isolation (see Day 1/2 of the plan).
"""

import heapq
from collections import defaultdict


def split_equal(total: int, user_ids: list[int]) -> dict[int, int]:
    n = len(user_ids)
    base = total // n
    remainder = total - base * n
    splits = {uid: base for uid in user_ids}
    for uid in user_ids[:remainder]:
        splits[uid] += 1
    return splits


def split_exact(total: int, amounts: dict[int, int]) -> dict[int, int]:
    if sum(amounts.values()) != total:
        raise ValueError("Exact amounts must sum to the total")
    return dict(amounts)


def split_percentage(total: int, percentages: dict[int, int]) -> dict[int, int]:
    if sum(percentages.values()) != 100:
        raise ValueError("Percentages must sum to 100")
    splits = {uid: (total * pct) // 100 for uid, pct in percentages.items()}
    remainder = total - sum(splits.values())
    for uid in list(splits.keys())[:remainder]:
        splits[uid] += 1
    return splits


def split_shares(total: int, shares: dict[int, int]) -> dict[int, int]:
    total_shares = sum(shares.values())
    splits = {uid: (total * s) // total_shares for uid, s in shares.items()}
    remainder = total - sum(splits.values())
    for uid in list(splits.keys())[:remainder]:
        splits[uid] += 1
    return splits


def compute_balances(expenses: list, settlements: list) -> dict[int, int]:
    """
    expenses: list of ORM Expense objects (with .payers and .splits loaded)
    settlements: list of ORM Settlement objects
    Returns {user_id: net_amount}, positive = is owed, negative = owes.
    """
    balance = defaultdict(int)

    for exp in expenses:
        for payer in exp.payers:
            balance[payer.user_id] += payer.amount_paid
        for split in exp.splits:
            balance[split.user_id] -= split.amount_owed

    for s in settlements:
        balance[s.paid_by] += s.amount
        balance[s.paid_to] -= s.amount

    return dict(balance)


def simplify_debts(balance: dict[int, int]) -> list[dict]:
    """
    Greedy min-transaction settlement. Returns a list of
    {"from_user": ..., "to_user": ..., "amount": ...}.
    """
    creditors = [(-amt, uid) for uid, amt in balance.items() if amt > 0]
    debtors = [(amt, uid) for uid, amt in balance.items() if amt < 0]
    heapq.heapify(creditors)
    heapq.heapify(debtors)

    transactions = []

    while creditors and debtors:
        neg_credit, cred_id = heapq.heappop(creditors)
        debt, debtor_id = heapq.heappop(debtors)
        credit = -neg_credit
        amount = min(credit, -debt)

        transactions.append({"from_user": debtor_id, "to_user": cred_id, "amount": amount})

        remaining_credit = credit - amount
        remaining_debt = debt + amount

        if remaining_credit > 0:
            heapq.heappush(creditors, (-remaining_credit, cred_id))
        if remaining_debt < 0:
            heapq.heappush(debtors, (remaining_debt, debtor_id))

    return transactions
