# Automated Bill Splitting API

A REST API that automatically divides shared expenses among a group of
users, calculates the minimum number of transactions needed to settle
everyone up, and pushes live updates to connected clients as expenses and
settlements happen.

**Features:**
- Four expense-splitting modes: equal, exact amount, percentage, and weighted shares
- Automatic debt simplification via a greedy min-transaction algorithm (verified to always net balances to zero)
- Real-time updates over WebSockets — connected clients see new expenses and updated balances instantly, no refresh or polling
- JWT-based authentication — group/expense actions are tied to the logged-in user, not client-supplied IDs
- 24 passing pytest tests covering rounding edge cases, multi-payer expenses, and algorithm correctness
- Built with FastAPI, SQLAlchemy, and SQLite

**Stack:** Python, FastAPI, SQLAlchemy, WebSockets, JWT (python-jose), bcrypt (passlib), pytest

---

## 1. Where everything goes (folder structure)

All files sit flat in one folder — no subfolders needed at this stage:

```
bill-splitter/
├── requirements.txt      <- list of packages to install
├── database.py           <- connects to the database
├── models.py              <- defines database tables
├── schemas.py              <- defines API request/response shapes
├── logic.py                 <- the actual splitting & debt algorithms
├── auth.py                   <- password hashing + JWT authentication
├── connection_manager.py      <- tracks WebSocket connections per group
├── main.py                     <- the API itself — this is what you run
├── test_logic.py                <- unit tests for logic.py
└── websocket_test.html           <- standalone page to test live updates
```

**Why this structure matters:** each file has exactly one job. `models.py`
never talks HTTP. `logic.py` never touches the database or the network.
`auth.py` handles identity, nothing else. `connection_manager.py` only
tracks who's listening. `main.py` is the only file that wires them together.
This separation is what makes `logic.py` fully unit-testable in under a
second, with zero server or database required — see `test_logic.py`.

## 2. Install and run, step by step

Open a terminal, `cd` into the `bill-splitter` folder, then:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Mac/Linux
.venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Then open **`http://127.0.0.1:8000/docs`** — FastAPI's auto-generated
interactive docs. Every endpoint can be tested there directly.

## 3. What is an API, concretely (in the context of this project)

An API endpoint is: **a URL + an HTTP method + a defined shape of data in,
and a defined shape of data out.**

- **URL** — e.g. `/groups/3/expenses` (`3` is a *path parameter*)
- **HTTP method** — `GET` reads data, `POST` creates something, `PUT`/`PATCH`
  updates, `DELETE` removes
- **Request body** — JSON sent with `POST`/`PUT`/`PATCH` requests
- **Response** — JSON back, plus a status code (`200` success, `400` bad
  request, `401` unauthorized, `404` not found)

Example, from `main.py`:
```python
@app.post("/groups/{group_id}/expenses", response_model=schemas.ExpenseOut)
async def create_expense(
    group_id: int,
    exp: schemas.ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
```
- `group_id: int` — pulled from the URL path automatically
- `exp: schemas.ExpenseCreate` — the JSON request body, auto-validated
  before the function even runs
- `db: Session = Depends(get_db)` — a database session, opened and closed
  automatically per request
- `current_user: models.User = Depends(auth.get_current_user)` — the real,
  verified user, decoded from their JWT token — not a value the client can fake

## 4. Test it end to end

**Auth flow:**
```bash
curl -X POST http://127.0.0.1:8000/auth/signup -H "Content-Type: application/json" \
  -d '{"name": "Alice", "email": "alice@example.com", "password": "test1234"}'

curl -X POST http://127.0.0.1:8000/auth/login \
  -d "username=alice@example.com&password=test1234"
# -> returns { "access_token": "...", "token_type": "bearer" }
```

Use the returned token as a `Bearer` token on subsequent requests (the
`/docs` UI's "Authorize" button does this for you automatically).

**Core flow** (via `/docs`, after authorizing as Alice):
1. `POST /groups` → `{"name": "Goa Trip"}`
2. Sign up more users, `POST /groups/{id}/members` to add them
3. `POST /groups/{id}/expenses` with `split_type` of `equal`, `exact`,
   `percentage`, or `shares`
4. `GET /groups/{id}/balances` → net amount owed/owed-to per person
5. `GET /groups/{id}/settle-suggestions` → minimum transactions to zero out

**Live updates:**
Open `websocket_test.html` directly in a browser (no server needed to view
it) in two separate tabs, connect both to the same group id, then create an
expense via `/docs` in a third tab. Both tabs update instantly with the new
expense and fresh balances — this is powered by the `/ws/groups/{group_id}`
WebSocket endpoint in `main.py`, broadcasting through `connection_manager.py`.

## 5. Running the tests

```bash
pip install pytest
pytest test_logic.py -v
```

24 tests covering rounding edge cases across all four split types,
multi-payer expenses, settlements, and correctness guarantees on the
debt-simplification algorithm (every result verified to net to exactly
zero and never exceed the theoretical minimum transaction count).

## 6. Possible next steps

- **Postgres** — swap `DATABASE_URL` in `database.py` from SQLite to a
  Postgres connection string; nothing else changes, since every other file
  talks to the database only through SQLAlchemy
- **Redis Pub/Sub** — needed if this is ever run as multiple server
  instances, so a broadcast from one instance reaches clients connected to
  another (the current WebSocket setup is single-process/in-memory)
- **Docker Compose** — run multiple app instances behind a load balancer
  locally, to demonstrate horizontal scaling