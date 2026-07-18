"""
Main API application. Run with:
    uvicorn main:app --reload
Then open http://127.0.0.1:8000/docs for interactive, auto-generated API docs.
"""

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

import models
import schemas
import logic
import auth
from database import engine, get_db, Base, SessionLocal
from connection_manager import manager

# Creates all tables defined in models.py, if they don't already exist.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Automated Bill Splitting API")


def _current_balances(group_id: int) -> list[dict]:
    """Recompute this group's balances fresh -- used both by the GET endpoint
    and by the broadcast, so the two are guaranteed to always agree."""
    db = SessionLocal()
    try:
        expenses = db.query(models.Expense).filter(models.Expense.group_id == group_id).all()
        settlements = db.query(models.Settlement).filter(models.Settlement.group_id == group_id).all()
        balances = logic.compute_balances(expenses, settlements)
        return [{"user_id": uid, "net_amount": amt} for uid, amt in balances.items()]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# WEBSOCKET -- live updates
# ---------------------------------------------------------------------------

@app.websocket("/ws/groups/{group_id}")
async def group_websocket(websocket: WebSocket, group_id: int):
    """
    Connect to this to receive live events for one group: new expenses,
    new settlements, and updated balances -- pushed the instant they happen,
    no polling or refresh needed.
    """
    await manager.connect(group_id, websocket)
    try:
        while True:
            # We don't require the client to send anything meaningful.
            # This just blocks here (without polling) until the client
            # sends something or disconnects -- which is how we detect
            # a closed connection and clean it up below.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(group_id, websocket)


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------

@app.post("/auth/signup", response_model=schemas.UserOut)
def signup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    db_user = models.User(
        name=user.name,
        email=user.email,
        password_hash=auth.hash_password(user.password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.post("/auth/login", response_model=schemas.TokenOut)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2PasswordRequestForm expects fields named "username" and "password" --
    # in the /docs UI, put the user's EMAIL into the "username" box.
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = auth.create_access_token(user_id=user.id)
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me", response_model=schemas.UserOut)
def read_current_user(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# GROUPS
# ---------------------------------------------------------------------------

@app.post("/groups", response_model=schemas.GroupOut)
def create_group(
    group: schemas.GroupCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    db_group = models.Group(name=group.name, created_by=current_user.id)
    db.add(db_group)
    db.commit()
    db.refresh(db_group)

    # creator automatically becomes a member
    db.add(models.GroupMember(group_id=db_group.id, user_id=current_user.id))
    db.commit()
    return db_group


@app.post("/groups/{group_id}/members")
def add_member(
    group_id: int,
    req: schemas.AddMemberRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    db.add(models.GroupMember(group_id=group_id, user_id=req.user_id))
    db.commit()
    return {"status": "added"}


# ---------------------------------------------------------------------------
# EXPENSES
# ---------------------------------------------------------------------------

@app.post("/groups/{group_id}/expenses", response_model=schemas.ExpenseOut)
async def create_expense(
    group_id: int,
    exp: schemas.ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # 1. Validate the payer amounts sum to the total -- NEVER trust the client's math
    if sum(exp.payers.values()) != exp.total_amount:
        raise HTTPException(status_code=400, detail="Payer amounts must sum to total_amount")

    # 2. Compute the split server-side, using the Day 1 logic functions
    if exp.split_type == "equal":
        if not exp.participants:
            raise HTTPException(status_code=400, detail="participants required for equal split")
        splits = logic.split_equal(exp.total_amount, exp.participants)
    elif exp.split_type == "exact":
        splits = logic.split_exact(exp.total_amount, exp.split_data)
    elif exp.split_type == "percentage":
        splits = logic.split_percentage(exp.total_amount, exp.split_data)
    elif exp.split_type == "shares":
        splits = logic.split_shares(exp.total_amount, exp.split_data)
    else:
        raise HTTPException(status_code=400, detail="Unknown split_type")

    # 3. Write expense + payers + splits together.
    #    SQLAlchemy's session batches these; nothing is committed until db.commit(),
    #    so if anything above raised an exception, nothing partial gets saved.
    db_expense = models.Expense(
        group_id=group_id,
        description=exp.description,
        total_amount=exp.total_amount,
        split_type=exp.split_type,
    )
    db.add(db_expense)
    db.flush()  # assigns db_expense.id without fully committing yet

    for user_id, amount in exp.payers.items():
        db.add(models.ExpensePayer(expense_id=db_expense.id, user_id=user_id, amount_paid=amount))

    for user_id, amount in splits.items():
        db.add(models.ExpenseSplit(expense_id=db_expense.id, user_id=user_id, amount_owed=amount))

    db.commit()
    db.refresh(db_expense)

    # Tell everyone currently watching this group: here's the new expense,
    # and here's what everyone's balance looks like now.
    await manager.broadcast(group_id, {
        "event": "expense_created",
        "expense": {
            "id": db_expense.id,
            "description": db_expense.description,
            "total_amount": db_expense.total_amount,
            "split_type": db_expense.split_type,
        },
        "balances": _current_balances(group_id),
    })

    return db_expense


@app.get("/groups/{group_id}/expenses", response_model=list[schemas.ExpenseOut])
def list_expenses(group_id: int, db: Session = Depends(get_db)):
    return db.query(models.Expense).filter(models.Expense.group_id == group_id).all()


# ---------------------------------------------------------------------------
# BALANCES & SETTLEMENTS
# ---------------------------------------------------------------------------

@app.get("/groups/{group_id}/balances", response_model=list[schemas.BalanceOut])
def get_balances(group_id: int, db: Session = Depends(get_db)):
    expenses = db.query(models.Expense).filter(models.Expense.group_id == group_id).all()
    settlements = db.query(models.Settlement).filter(models.Settlement.group_id == group_id).all()

    balances = logic.compute_balances(expenses, settlements)
    return [{"user_id": uid, "net_amount": amt} for uid, amt in balances.items()]


@app.get("/groups/{group_id}/settle-suggestions", response_model=list[schemas.SettlementSuggestion])
def get_settle_suggestions(group_id: int, db: Session = Depends(get_db)):
    expenses = db.query(models.Expense).filter(models.Expense.group_id == group_id).all()
    settlements = db.query(models.Settlement).filter(models.Settlement.group_id == group_id).all()

    balances = logic.compute_balances(expenses, settlements)
    return logic.simplify_debts(balances)


@app.post("/groups/{group_id}/settlements")
async def record_settlement(
    group_id: int,
    s: schemas.SettlementCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    db.add(models.Settlement(
        group_id=group_id,
        paid_by=current_user.id,   # you can only record yourself as having paid
        paid_to=s.paid_to,
        amount=s.amount,
    ))
    db.commit()

    await manager.broadcast(group_id, {
        "event": "settlement_recorded",
        "settlement": {"paid_by": current_user.id, "paid_to": s.paid_to, "amount": s.amount},
        "balances": _current_balances(group_id),
    })

    return {"status": "recorded"}
