"""
Pydantic schemas. These are NOT database tables -- they define the JSON
shape that comes IN to your API (request bodies) and goes OUT (responses).
FastAPI uses these to auto-validate incoming JSON and auto-generate docs.
"""

from pydantic import BaseModel, EmailStr
from typing import Literal


# ---------- Users & Auth ----------

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # lets this read directly from an ORM object


# ---------- Groups ----------

class GroupCreate(BaseModel):
    name: str
    # created_by is no longer sent by the client -- it's taken from the
    # authenticated user's token, so no one can create a group "as" someone else

class GroupOut(BaseModel):
    id: int
    name: str
    created_by: int

    class Config:
        from_attributes = True

class AddMemberRequest(BaseModel):
    user_id: int


# ---------- Expenses ----------

class ExpenseCreate(BaseModel):
    description: str
    total_amount: int  # in smallest currency unit -- e.g. paise
    split_type: Literal["equal", "exact", "percentage", "shares"]

    # who paid, and how much each of them paid (must sum to total_amount)
    payers: dict[int, int]

    # meaning depends on split_type:
    #   equal      -> list of user_ids in `participants`, this field ignored
    #   exact      -> {user_id: amount_owed}
    #   percentage -> {user_id: percentage}, must sum to 100
    #   shares     -> {user_id: share_count}
    split_data: dict[int, int] = {}
    participants: list[int] = []  # only used when split_type == "equal"

class ExpenseOut(BaseModel):
    id: int
    description: str
    total_amount: int
    split_type: str

    class Config:
        from_attributes = True


# ---------- Balances & Settlements ----------

class BalanceOut(BaseModel):
    user_id: int
    net_amount: int  # positive = is owed money, negative = owes money

class SettlementSuggestion(BaseModel):
    from_user: int
    to_user: int
    amount: int

class SettlementCreate(BaseModel):
    # paid_by comes from the authenticated user's token, not the client
    paid_to: int
    amount: int
