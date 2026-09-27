> Historical implementation plan: retained for project background. Some original assumptions (CSV replacement, Python version, launch/test entry point, and settlement optimality) were superseded. Follow README.md for the current setup and behavior. The existing CSV was preserved during the launch repair.

# Smart Expense Splitter & Analytics Dashboard — Implementation Plan

## Top-Level Overview

**Goal:** Build a single-file Streamlit web application (`app.py`) that lets a group of friends
record shared expenses stored in a plain-text `expenses.csv`, calculate who owes whom,
and explore spending through an interactive analytics dashboard.

**Scope:**
- Create a fresh plain-text `expenses.csv` with 10–15 realistic sample rows for Amit, Neha,
  and Rahul covering all 7 categories. The current binary Excel file is replaced.
- Implement all logic (storage, calculation, UI) in one `app.py`. No separate test file.
- Deliver `requirements.txt` and `README.md` alongside `app.py`.

**Out of scope:** Authentication, multi-group support, currency conversion, database storage,
email summaries, payment gateways.

**Confirmed decisions:**
- **Default participants (empty CSV fallback):** Amit, Neha, Rahul.
- **Dynamic participants:** Derived from `paid_by` + `split_between` columns when CSV has data.
- **Categories:** Food, Travel, Stay, Activities, Shopping, Utilities, Other.
- **Tests:** All inside `app.py` in `run_tests()`, guarded by `if __name__ == "__main__"`.
- **No separate `test_app.py`.**

**Key constraints:**
- `expenses.csv` must be plain UTF-8 CSV throughout; app uses `pandas.read_csv` / `to_csv`.
- Money must be rounded to two decimal places everywhere.
- No duplicate entries from Streamlit widget reruns.
- All code must be readable and explainable by an engineering student.

---

## Architecture Overview

```
app.py
├── DATA LAYER        load_data() / save_expense()
├── CALCULATION LAYER calculate_balances() / calculate_settlements()
├── ANALYTICS LAYER   compute_kpis() / summarise_by_*()
└── UI LAYER          tab: Dashboard | Add Expense | Balances | Settlements
```

`expenses.csv` is the single source of truth — loaded fresh on each Streamlit run and appended
to on valid form submission.

---

## Sub-Tasks

---

### Sub-Task 1 — Create plain-text `expenses.csv` with sample data

**Intent:**
Replace the current binary Excel file with a properly formatted UTF-8 CSV so the app can read
and write it with `pandas.read_csv` / `DataFrame.to_csv`. Seeding it with realistic sample rows
lets every later feature be developed and tested immediately.

**Expected Outcomes:**
- `expenses.csv` is a readable plain-text file.
- It has the header row: `date,description,category,amount,paid_by,split_between`.
- It contains 10–15 sample rows for participants Amit, Neha, Rahul covering all 7 categories
  (Food, Travel, Stay, Activities, Shopping, Utilities, Other) so dashboard charts are rich.
- `split_between` uses the `|` separator (e.g. `Amit|Neha|Rahul`).
- Dates span at least 2–3 weeks so the daily spending trend chart is meaningful.

**Todo List:**
- [ ] Write a new `expenses.csv` with the correct header and 10–15 sample rows.
- [ ] Ensure all 7 categories are represented at least once.
- [ ] Ensure each of Amit, Neha, Rahul appears as `paid_by` at least twice.
- [ ] Verify the file is plain UTF-8 text (no BOM, no binary content).

**Relevant Context:**
- Current file (`expenses.csv`) is a ZIP-compressed Excel workbook — must be fully overwritten.
- Columns: `date` (YYYY-MM-DD), `description` (string), `category` (string), `amount` (float),
  `paid_by` (string), `split_between` (pipe-delimited names, e.g. `Amit|Neha|Rahul`).

**Status:** [x] done

---

### Sub-Task 2 — Implement the Data Layer (`load_data` / `save_expense`)

**Intent:**
Create the two functions that mediate all access to `expenses.csv`, so the rest of the app
never touches the filesystem directly. Centralising I/O makes validation and error handling
straightforward.

**Expected Outcomes:**
- `load_data()` returns a `DataFrame` with the six columns; returns an empty `DataFrame` with
  those columns when the file is missing or empty.
- `save_expense(row_dict)` appends one validated row to the CSV without rewriting the whole
  file (use `mode='a'`, `header=False` when the file already has content).
- `amount` is always stored rounded to 2 decimal places.
- Function-level docstrings explain what each function does.

**Todo List:**
- [ ] Write `load_data()` with try/except for missing file and empty file edge cases.
- [ ] Write `save_expense(row_dict)` with append logic and header detection.
- [ ] Add column dtype enforcement (`amount` → float, `date` → string).
- [ ] Write a short inline comment block explaining the CSV schema.

**Relevant Context:**
- `expenses.csv` path is a module-level constant `CSV_FILE = "expenses.csv"`.
- Pandas `read_csv` with `dtype={"amount": float}` prevents silent type coercion.

**Status:** [x] done

---

### Sub-Task 3 — Implement the Calculation Layer (`calculate_balances` / `calculate_settlements`)

**Intent:**
Produce the financial logic that turns raw expense rows into per-person balances and a minimal
set of payment instructions. This is the core of a Splitwise-style app.

**Expected Outcomes:**
- `calculate_balances(df)` returns a `DataFrame` with columns:
  `person, total_paid, total_share, net_balance`.
  Net balance = total_paid − total_share. Positive → should receive money; negative → owes money.
  Sum of all net balances equals zero (verified inside the function with an assert or warning).
- `calculate_settlements(balances_df)` returns a list of dicts
  `[{"from": X, "to": Y, "amount": Z}, ...]` that resolves all debts with the minimum number
  of transactions (greedy creditor-debtor matching).
- All monetary values rounded to 2 decimal places.

**Todo List:**
- [ ] Write `calculate_balances(df)`:
  - Expand `split_between` pipe-separated names into one row per participant per expense.
  - Compute each participant's share = `amount / number_of_participants`.
  - Aggregate `total_paid` (sum where `paid_by == person`) and `total_share` per person.
  - Compute `net_balance = total_paid - total_share`, rounded to 2 dp.
- [ ] Write `calculate_settlements(balances_df)`:
  - Separate debtors (net_balance < 0) and creditors (net_balance > 0).
  - Greedily match largest debtor to largest creditor until all balances reach 0.
  - Return list of `{"from", "to", "amount"}` dicts.
- [ ] Add a check that the sum of all net balances is ≈ 0 (within floating-point tolerance).

**Relevant Context:**
- The greedy settlement algorithm is O(n log n) and sufficient for small groups.
- Use `round(..., 2)` consistently; avoid f-string formatting for intermediate calculations.

**Status:** [x] done

---

### Sub-Task 4 — Implement the Analytics Layer (KPIs and summaries)

**Intent:**
Provide the computed metrics and aggregations that power the dashboard, keeping all
Pandas logic isolated from the UI layer.

**Expected Outcomes:**
- `compute_kpis(df)` returns a dict with keys:
  `total_expenses`, `num_transactions`, `avg_expense`, `top_category`, `top_spender`.
- `summarise_by_category(df)` returns a `DataFrame` of `{category, total_amount}`.
- `summarise_by_date(df)` returns a `DataFrame` of `{date, total_amount}` sorted by date.
- `summarise_by_person(df)` returns a `DataFrame` of `{person, total_paid}`.
- Each function handles an empty `DataFrame` gracefully (returns empty result or zeroed KPIs).

**Todo List:**
- [ ] Write `compute_kpis(df)` with empty-df guard.
- [ ] Write `summarise_by_category(df)`.
- [ ] Write `summarise_by_date(df)` with date sorting.
- [ ] Write `summarise_by_person(df)`.
- [ ] Add a `generate_insights(df, kpis)` function that returns 2–3 plain-English insight
      strings derived from actual data (e.g. highest-spending category, biggest payer).

**Relevant Context:**
- `date` column is stored as a string (YYYY-MM-DD); convert to `pd.to_datetime` only for
  sorting and charting, not for storage.
- `top_spender` is determined from `paid_by` column, not from share calculation.

**Status:** [x] done

---

### Sub-Task 5 — Build the Streamlit UI (four tabs)

**Intent:**
Wire all layers together in a clean, single-file Streamlit app with four labelled tabs.
The UI must be beginner-friendly: clear headings, sensible form defaults, and informative
success/error messages.

**Expected Outcomes:**
- `st.set_page_config` sets a meaningful title and wide layout.
- Four tabs: **Dashboard**, **Add Expense**, **Balances & Splits**, **Settlements**.
- **Dashboard tab:** Five KPI metric cards; Plotly pie chart (category distribution);
  Plotly line/bar chart (daily spending trend); Plotly bar chart (amount paid per person).
  Shows "No data yet" message when CSV is empty.
- **Add Expense tab:** Form with date picker, text input (description), selectbox (category),
  number input (amount ≥ 0.01), selectbox (paid_by), multiselect (split_between participants).
  On submit: validates inputs, calls `save_expense`, shows success message, refreshes data
  using `st.rerun()`. Duplicate prevention via `st.session_state` form-submission flag.
- **Balances & Splits tab:** Table showing per-person `total_paid`, `total_share`,
  `net_balance` with colour hint (green = owed money, red = owes money).
- **Settlements tab:** Clear "X pays Y: ₹Z" statements for each settlement transaction;
  confirmation that all balances are cleared.

**Todo List:**
- [ ] Add module-level constants: `CSV_FILE`, `CATEGORIES`, `PARTICIPANTS`.
- [ ] Structure the file: imports → constants → data layer → calculation layer →
      analytics layer → UI (page config → load data → tabs).
- [ ] Build Dashboard tab with KPI cards and three Plotly charts.
- [ ] Build Add Expense tab with form, validation, dedup guard, and `st.rerun()` after save.
- [ ] Build Balances & Splits tab with styled balance table.
- [ ] Build Settlements tab with settlement list and zero-balance confirmation.
- [ ] Add a sidebar with app title, brief description, and current participant list.

**Relevant Context:**
- `PARTICIPANTS` list drives both the payer dropdown and the split multiselect.
- Derive the participant list dynamically from all unique names that appear in
  `paid_by` and `split_between` columns of the loaded data; fallback default when CSV empty:
  `["Amit", "Neha", "Rahul"]`.
- `CATEGORIES = ["Food", "Travel", "Stay", "Activities", "Shopping", "Utilities", "Other"]`.
- Use `st.session_state["last_submitted"]` to prevent duplicate saves on reruns.
- Plotly charts: use `plotly.express` for simplicity.

**Status:** [x] done

---

### Sub-Task 6 — Create `requirements.txt` and `README.md`

**Intent:**
Provide the supporting files needed to install dependencies and understand the project.

**Expected Outcomes:**
- `requirements.txt` lists exact packages: `streamlit`, `pandas`, `plotly`.
- `README.md` contains: project title, description, setup instructions (pip install, run command),
  feature list, CSV schema, and a note on how to reset data.

**Todo List:**
- [ ] Write `requirements.txt` with the three package names (no pinned versions required for
      a beginner project, but include a comment about Python version).
- [ ] Write `README.md` covering: what the app does, how to install, how to run, CSV format,
      adding/resetting data.

**Relevant Context:**
- Run command: `streamlit run app.py`
- Python ≥ 3.8 is sufficient.

**Status:** [x] done

---

### Sub-Task 7 — Add inline tests / validation checks

**Intent:**
Provide lightweight, runnable verification that the core financial logic is correct —
without introducing a full test framework. All tests live inside `app.py`.

**Expected Outcomes:**
- A `run_tests()` function inside `app.py` that:
  - Creates a small in-memory `DataFrame` for Amit, Neha, Rahul with known values.
  - Asserts `calculate_balances` produces correct `net_balance` values.
  - Asserts sum of all net balances ≈ 0.
  - Asserts `calculate_settlements` produces transactions that clear all balances.
  - Asserts per-person share equals `amount / len(participants)`.
- Running `python app.py` prints "All tests passed." or raises `AssertionError` with message.
- No separate `test_app.py` is created.

**Todo List:**
- [ ] Write `run_tests()` inside `app.py` with at least four assert-based test cases.
- [ ] Guard invocation with `if __name__ == "__main__": run_tests()`.
- [ ] Cover: correct per-person share (amount / n participants).
- [ ] Cover: sum of net balances = 0.
- [ ] Cover: settlements clear all outstanding balances.
- [ ] Cover: edge case — one person pays for all three, others owe equal shares.

**Relevant Context:**
- No external test library needed — plain `assert` statements with descriptive messages.
- Keep test data minimal (3 people, 3 expenses matching Amit/Neha/Rahul defaults).

**Status:** [x] done

---

## File Map After Implementation

```
Smart_expense_splitter/
├── app.py              ← all Python code (UI + logic)
├── expenses.csv        ← plain-text CSV data store
├── requirements.txt    ← pip dependencies
└── README.md           ← setup and usage guide
```

---

## Execution Order

Sub-tasks must be executed in this order because each depends on the previous:

1. **Sub-Task 1** — valid CSV must exist before any code can be tested.
2. **Sub-Task 2** — data layer is the foundation for all other layers.
3. **Sub-Task 3** — balance/settlement calculations depend on loaded data.
4. **Sub-Task 4** — analytics build on the same loaded data.
5. **Sub-Task 5** — UI assembles all three layers; must come last.
6. **Sub-Task 6** — docs can be written any time but logically come after code.
7. **Sub-Task 7** — tests validate the finished logic.
