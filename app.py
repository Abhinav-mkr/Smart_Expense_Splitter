"""
Smart Expense Splitter & Analytics Dashboard
=============================================
A Splitwise-style Streamlit app for tracking group expenses,
calculating who owes whom, and exploring spending analytics.

Technology stack: Python, Streamlit, Pandas, Plotly, CSV storage.

Run with:  streamlit run app.py
Test with: python app.py --test
"""

import os
import sys
from pathlib import Path
import math
import pandas as pd
import plotly.express as px
import streamlit as st

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

CSV_FILE = Path(__file__).resolve().parent / "expenses.csv"

# Categories available in the "Add Expense" form
CATEGORIES = ["Food", "Travel", "Stay", "Activities", "Shopping", "Utilities", "Other"]

# Default participants used when the CSV is empty
DEFAULT_PARTICIPANTS = ["Amit", "Neha", "Rahul"]

# CSV column names — kept as a constant so every function uses the same names
CSV_COLUMNS = ["date", "description", "category", "amount", "paid_by", "split_between"]


# ---------------------------------------------------------------------------
# DATA LAYER
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """
    Load expenses from expenses.csv and return a DataFrame.

    Returns an empty DataFrame with the correct columns if the file
    does not exist or contains no data rows.
    """
    empty_df = pd.DataFrame(columns=CSV_COLUMNS)

    if not os.path.exists(CSV_FILE):
        return empty_df

    try:
        df = pd.read_csv(CSV_FILE, dtype={"amount": float})
        # Validate that all expected columns are present
        if df.empty or not all(col in df.columns for col in CSV_COLUMNS):
            return empty_df
        # Ensure amount is numeric and date is a string
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").round(2)
        df["date"] = df["date"].astype(str)
        df = df.dropna(subset=["amount"])  # Drop rows with unreadable amounts
        return df.reset_index(drop=True)
    except (pd.errors.EmptyDataError, Exception):
        return empty_df


def save_expense(row: dict) -> None:
    """
    Append a single validated expense row to expenses.csv.

    If the file does not exist yet, the header is written first.
    The amount is stored rounded to 2 decimal places.
    """
    row["amount"] = round(float(row["amount"]), 2)

    # A header-only CSV already has its header; do not append it again.
    write_header = not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0

    new_row = pd.DataFrame([row], columns=CSV_COLUMNS)
    new_row.to_csv(CSV_FILE, mode="a", header=write_header, index=False)


def get_participants(df: pd.DataFrame) -> list:
    """
    Derive the participant list dynamically from the loaded DataFrame.

    Collects all unique names that appear in paid_by or split_between.
    Falls back to DEFAULT_PARTICIPANTS when the DataFrame is empty.
    """
    if df.empty:
        return DEFAULT_PARTICIPANTS[:]

    names = set()

    # Names from paid_by column
    for name in df["paid_by"].dropna():
        names.add(name.strip())

    # Names from split_between column (pipe-separated)
    for entry in df["split_between"].dropna():
        for name in str(entry).split("|"):
            stripped = name.strip()
            if stripped:
                names.add(stripped)

    return sorted(names) if names else DEFAULT_PARTICIPANTS[:]


# ---------------------------------------------------------------------------
# CALCULATION LAYER
# ---------------------------------------------------------------------------

def calculate_balances(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate per-person financial balances from the expense DataFrame.

    For each expense, each participant in split_between gets an equal share
    (amount / number of participants).

    Returns a DataFrame with columns:
        person, total_paid, total_share, net_balance

    net_balance = total_paid - total_share
      > 0  → this person should receive money
      < 0  → this person owes money
      = 0  → settled
    """
    if df.empty:
        return pd.DataFrame(columns=["person", "total_paid", "total_share", "net_balance"])

    # Build a list of per-person share entries
    share_rows = []
    for _, expense in df.iterrows():
        participants = [p.strip() for p in str(expense["split_between"]).split("|") if p.strip()]
        if not participants:
            continue
        share = round(float(expense["amount"]) / len(participants), 2)
        for person in participants:
            share_rows.append({"person": person, "share": share})

    if not share_rows:
        return pd.DataFrame(columns=["person", "total_paid", "total_share", "net_balance"])

    shares_df = pd.DataFrame(share_rows)
    total_share = shares_df.groupby("person")["share"].sum().reset_index()
    total_share.columns = ["person", "total_share"]

    # Aggregate how much each person paid
    paid_df = df.groupby("paid_by")["amount"].sum().reset_index()
    paid_df.columns = ["person", "total_paid"]

    # Merge paid and share on person name (outer join captures everyone)
    balances = pd.merge(total_share, paid_df, on="person", how="outer").fillna(0.0)
    balances["total_paid"] = balances["total_paid"].round(2)
    balances["total_share"] = balances["total_share"].round(2)
    balances["net_balance"] = (balances["total_paid"] - balances["total_share"]).round(2)

    return balances.sort_values("person").reset_index(drop=True)


def calculate_settlements(balances_df: pd.DataFrame) -> list:
    """
    Calculate the minimum set of payment transactions to settle all debts.

    Uses a greedy algorithm:
      1. Sort creditors (net_balance > 0) and debtors (net_balance < 0).
      2. Match the largest debtor with the largest creditor.
      3. Record a transaction, reduce both balances, repeat.

    Returns a list of dicts: [{"from": debtor, "to": creditor, "amount": value}, ...]
    """
    if balances_df.empty:
        return []

    # Work with mutable copies rounded to 2 dp
    creditors = (
        balances_df[balances_df["net_balance"] > 0.005]
        [["person", "net_balance"]]
        .copy()
        .sort_values("net_balance", ascending=False)
        .reset_index(drop=True)
    )
    debtors = (
        balances_df[balances_df["net_balance"] < -0.005]
        [["person", "net_balance"]]
        .copy()
        .sort_values("net_balance")  # most negative first
        .reset_index(drop=True)
    )

    transactions = []
    i, j = 0, 0  # indices into debtors and creditors

    while i < len(debtors) and j < len(creditors):
        debt = round(abs(debtors.loc[i, "net_balance"]), 2)
        credit = round(creditors.loc[j, "net_balance"], 2)

        # The transaction amount is the smaller of the two
        amount = round(min(debt, credit), 2)
        if amount > 0.005:
            transactions.append({
                "from": debtors.loc[i, "person"],
                "to": creditors.loc[j, "person"],
                "amount": amount,
            })

        # Reduce both balances
        debtors.loc[i, "net_balance"] = round(debtors.loc[i, "net_balance"] + amount, 2)
        creditors.loc[j, "net_balance"] = round(creditors.loc[j, "net_balance"] - amount, 2)

        # Move pointer(s) forward when a balance reaches zero
        if abs(debtors.loc[i, "net_balance"]) < 0.005:
            i += 1
        if abs(creditors.loc[j, "net_balance"]) < 0.005:
            j += 1

    return transactions


# ---------------------------------------------------------------------------
# ANALYTICS LAYER
# ---------------------------------------------------------------------------

def compute_kpis(df: pd.DataFrame) -> dict:
    """
    Compute top-level KPI metrics from the expense DataFrame.

    Returns a dict with keys:
        total_expenses   – sum of all amounts
        num_transactions – number of expense rows
        avg_expense      – average expense amount
        top_category     – category with highest total spending
        top_spender      – person who paid the most
    """
    if df.empty:
        return {
            "total_expenses": 0.0,
            "num_transactions": 0,
            "avg_expense": 0.0,
            "top_category": "N/A",
            "top_spender": "N/A",
        }

    return {
        "total_expenses": round(df["amount"].sum(), 2),
        "num_transactions": len(df),
        "avg_expense": round(df["amount"].mean(), 2),
        "top_category": df.groupby("category")["amount"].sum().idxmax(),
        "top_spender": df.groupby("paid_by")["amount"].sum().idxmax(),
    }


def summarise_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return total spending per category, sorted descending by amount.
    """
    if df.empty:
        return pd.DataFrame(columns=["category", "total_amount"])

    result = (
        df.groupby("category")["amount"]
        .sum()
        .round(2)
        .reset_index()
        .rename(columns={"amount": "total_amount"})
        .sort_values("total_amount", ascending=False)
        .reset_index(drop=True)
    )
    return result


def summarise_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return total spending per date, sorted chronologically.
    """
    if df.empty:
        return pd.DataFrame(columns=["date", "total_amount"])

    result = (
        df.groupby("date")["amount"]
        .sum()
        .round(2)
        .reset_index()
        .rename(columns={"amount": "total_amount"})
    )
    # Sort by date properly
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.sort_values("date").reset_index(drop=True)
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    return result


def summarise_by_person(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return total amount paid per person, sorted descending.
    """
    if df.empty:
        return pd.DataFrame(columns=["person", "total_paid"])

    result = (
        df.groupby("paid_by")["amount"]
        .sum()
        .round(2)
        .reset_index()
        .rename(columns={"paid_by": "person", "amount": "total_paid"})
        .sort_values("total_paid", ascending=False)
        .reset_index(drop=True)
    )
    return result


def generate_insights(df: pd.DataFrame, kpis: dict) -> list:
    """
    Generate 2–3 plain-English insight strings from the actual data.

    Returns a list of strings suitable for display in the dashboard.
    """
    if df.empty:
        return ["No expense data available yet. Add your first expense to see insights."]

    insights = []

    # Insight 1 – top spending category
    cat_summary = summarise_by_category(df)
    if not cat_summary.empty:
        top_cat = cat_summary.iloc[0]
        insights.append(
            f"💸 The highest spending category is **{top_cat['category']}** "
            f"(₹{top_cat['total_amount']:,.2f})."
        )

    # Insight 2 – biggest payer
    person_summary = summarise_by_person(df)
    if not person_summary.empty:
        top_person = person_summary.iloc[0]
        insights.append(
            f"🏆 **{top_person['person']}** has paid the most so far "
            f"(₹{top_person['total_paid']:,.2f})."
        )

    # Insight 3 – average expense
    insights.append(
        f"📊 The average expense amount is ₹{kpis['avg_expense']:,.2f} "
        f"across {kpis['num_transactions']} transaction(s)."
    )

    return insights


# ---------------------------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------------------------

def render_dashboard(df: pd.DataFrame) -> None:
    """Render the Dashboard tab with KPI cards and interactive charts."""
    st.header("📊 Dashboard")

    kpis = compute_kpis(df)

    if df.empty:
        st.info("No expense data yet. Go to the **Add Expense** tab to record your first expense.")
        return

    # --- KPI Cards ---
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Expenses", f"₹{kpis['total_expenses']:,.2f}")
    col2.metric("Transactions", kpis["num_transactions"])
    col3.metric("Avg Expense", f"₹{kpis['avg_expense']:,.2f}")
    col4.metric("Top Category", kpis["top_category"])
    col5.metric("Top Spender", kpis["top_spender"])

    st.divider()

    # --- Row 1: Category pie + Daily trend ---
    left, right = st.columns(2)

    with left:
        st.subheader("Spending by Category")
        cat_data = summarise_by_category(df)
        fig_pie = px.pie(
            cat_data,
            names="category",
            values="total_amount",
            hole=0.35,
            color_discrete_sequence=px.colors.qualitative.Set3,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(margin=dict(t=10, b=10), showlegend=True)
        st.plotly_chart(fig_pie, width="stretch")

    with right:
        st.subheader("Daily Spending Trend")
        date_data = summarise_by_date(df)
        fig_line = px.bar(
            date_data,
            x="date",
            y="total_amount",
            labels={"date": "Date", "total_amount": "Amount (₹)"},
            color_discrete_sequence=["#4C78A8"],
        )
        fig_line.update_layout(margin=dict(t=10, b=10), xaxis_tickangle=-45)
        st.plotly_chart(fig_line, width="stretch")

    # --- Row 2: Per-person contribution ---
    st.subheader("Amount Paid by Each Person")
    person_data = summarise_by_person(df)
    fig_bar = px.bar(
        person_data,
        x="person",
        y="total_paid",
        text="total_paid",
        labels={"person": "Person", "total_paid": "Total Paid (₹)"},
        color="person",
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    fig_bar.update_traces(texttemplate="₹%{text:,.2f}", textposition="outside")
    fig_bar.update_layout(showlegend=False, margin=dict(t=10, b=10))
    st.plotly_chart(fig_bar, width="stretch")

    # --- Insights ---
    st.divider()
    st.subheader("💡 Insights")
    for insight in generate_insights(df, kpis):
        st.markdown(f"- {insight}")


def render_add_expense(df: pd.DataFrame, participants: list) -> None:
    """Render the Add Expense tab with a validated form."""
    st.header("➕ Add Expense")

    with st.form(key="add_expense_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            expense_date = st.date_input("Date")
            description = st.text_input("Description", placeholder="e.g. Lunch at Cafe")
            category = st.selectbox("Category", CATEGORIES)

        with col2:
            amount = st.number_input(
                "Amount (₹)", min_value=0.01, step=0.01, format="%.2f", value=100.00
            )
            paid_by = st.selectbox("Paid By", participants)
            split_between = st.multiselect(
                "Split Between",
                participants,
                default=participants,
                help="Select everyone sharing this expense.",
            )

        submitted = st.form_submit_button("💾 Save Expense", width="stretch")

    if submitted:
        # --- Input validation ---
        errors = []

        if not description.strip():
            errors.append("Description cannot be empty.")
        if amount <= 0:
            errors.append("Amount must be greater than zero.")
        if not split_between:
            errors.append("Please select at least one participant to split with.")
        if paid_by not in participants:
            errors.append(f"Payer '{paid_by}' is not a recognised participant.")

        if errors:
            for error in errors:
                st.error(error)
            return

        # --- Duplicate prevention via session state ---
        # Build a unique key for this submission
        submission_key = f"{expense_date}|{description.strip()}|{amount}|{paid_by}"
        if st.session_state.get("last_submitted") == submission_key:
            st.warning("This expense was already saved. Refresh the page to add another.")
            return

        # --- Save to CSV ---
        new_row = {
            "date": str(expense_date),
            "description": description.strip(),
            "category": category,
            "amount": amount,
            "paid_by": paid_by,
            "split_between": "|".join(split_between),
        }
        save_expense(new_row)

        # Record what was just saved to prevent duplicate submissions
        st.session_state["last_submitted"] = submission_key

        st.success(
            f"✅ Expense saved: **{description.strip()}** — "
            f"₹{amount:,.2f} paid by **{paid_by}**, "
            f"split among {', '.join(split_between)}."
        )

        # Refresh the page so the dashboard reflects the new data
        st.rerun()


def render_balances(df: pd.DataFrame) -> None:
    """Render the Balances & Splits tab with a colour-hinted balance table."""
    st.header("⚖️ Balances & Splits")

    if df.empty:
        st.info("No expenses recorded yet.")
        return

    balances = calculate_balances(df)

    if balances.empty:
        st.info("No balance data to display.")
        return

    # Verify that net balances sum to zero (should always hold)
    net_sum = round(balances["net_balance"].sum(), 2)
    if abs(net_sum) > 0.05:
        st.warning(f"⚠️ Net balance sum is ₹{net_sum:.2f} (should be 0). Check your data.")

    # Display styled table
    st.markdown("**Net Balance** = Total Paid − Total Share")
    st.markdown(
        "🟢 Positive = should **receive** money &nbsp;|&nbsp; "
        "🔴 Negative = **owes** money"
    )

    # Format and display
    display_df = balances.copy()
    display_df["total_paid"] = display_df["total_paid"].apply(lambda x: f"₹{x:,.2f}")
    display_df["total_share"] = display_df["total_share"].apply(lambda x: f"₹{x:,.2f}")

    # Colour code the net_balance column
    def colour_balance(val):
        colour = "green" if val > 0 else ("red" if val < 0 else "gray")
        return f"color: {colour}; font-weight: bold"

    styled = (
        balances[["person", "total_paid", "total_share", "net_balance"]]
        .style
        .format({"total_paid": "₹{:,.2f}", "total_share": "₹{:,.2f}", "net_balance": "₹{:,.2f}"})
        .map(colour_balance, subset=["net_balance"])
    )
    st.dataframe(styled, width="stretch", hide_index=True)

    st.divider()
    st.subheader("All Expenses")
    st.dataframe(
        df.rename(columns={
            "date": "Date", "description": "Description", "category": "Category",
            "amount": "Amount (₹)", "paid_by": "Paid By", "split_between": "Split Between"
        }),
        width="stretch",
        hide_index=True,
    )


def render_settlements(df: pd.DataFrame) -> None:
    """Render the Settlements tab with payment instructions."""
    st.header("🤝 Settlements")

    if df.empty:
        st.info("No expenses recorded yet.")
        return

    balances = calculate_balances(df)
    settlements = calculate_settlements(balances)

    if not settlements:
        st.success("✅ Everyone is settled up — no payments needed!")
        return

    st.markdown(
        "These are the **minimum transactions** needed to clear all balances. "
        "Each amount is rounded to 2 decimal places."
    )

    for txn in settlements:
        st.markdown(
            f"💸 **{txn['from']}** pays **{txn['to']}** → ₹{txn['amount']:,.2f}"
        )

    # Verification: simulate applying settlements and confirm everything nets to zero
    st.divider()
    st.subheader("✅ Settlement Verification")

    # Apply settlements to balances to check they clear
    check = balances.set_index("person")["net_balance"].to_dict()
    for txn in settlements:
        check[txn["from"]] = round(check.get(txn["from"], 0) + txn["amount"], 2)
        check[txn["to"]] = round(check.get(txn["to"], 0) - txn["amount"], 2)

    all_clear = all(abs(v) < 0.05 for v in check.values())
    if all_clear:
        st.success("All balances will be cleared after the above payments. ✔")
    else:
        remaining = {k: v for k, v in check.items() if abs(v) >= 0.05}
        st.warning(f"Some balances remain after settlement: {remaining}")


# ---------------------------------------------------------------------------
# MAIN — PAGE CONFIG AND APP LAYOUT
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the Streamlit app."""
    st.set_page_config(
        page_title="Smart Expense Splitter",
        page_icon="💰",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # --- Sidebar ---
    with st.sidebar:
        st.title("💰 Smart Expense Splitter")
        st.caption("Track group expenses, split bills equally, and settle up fast.")
        st.divider()

        df = load_data()
        participants = get_participants(df)

        st.subheader("👥 Participants")
        for p in participants:
            st.markdown(f"- {p}")

        st.divider()
        st.caption("Data stored in `expenses.csv`")
        st.caption(f"Total rows: {len(df)}")

    # --- Reload data (sidebar may have already loaded it, but tabs need a fresh reference) ---
    df = load_data()
    participants = get_participants(df)

    # --- Tabs ---
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📊 Dashboard", "➕ Add Expense", "⚖️ Balances & Splits", "🤝 Settlements"]
    )

    with tab1:
        render_dashboard(df)

    with tab2:
        render_add_expense(df, participants)

    with tab3:
        render_balances(df)

    with tab4:
        render_settlements(df)


# ---------------------------------------------------------------------------
# INLINE TESTS  (run with: python app.py --test)
# ---------------------------------------------------------------------------

def run_tests() -> None:
    """
    Lightweight assertion-based tests for the core financial logic.

    Run via: python app.py --test
    Tests run only when explicitly requested, without rendering the web app.
    """
    print("Running tests...")

    # -----------------------------------------------------------------------
    # Test data: 3 expenses for Amit, Neha, Rahul
    # -----------------------------------------------------------------------
    test_data = {
        "date":         ["2025-06-01", "2025-06-02", "2025-06-03"],
        "description":  ["Flight",     "Hotel",      "Dinner"],
        "category":     ["Travel",     "Stay",       "Food"],
        "amount":       [3000.00,      1500.00,      900.00],
        "paid_by":      ["Amit",       "Neha",       "Rahul"],
        "split_between":["Amit|Neha|Rahul", "Amit|Neha|Rahul", "Amit|Neha|Rahul"],
    }
    df = pd.DataFrame(test_data)
    total = 3000.00 + 1500.00 + 900.00  # = 5400.00

    # -----------------------------------------------------------------------
    # Test 1: Correct per-person share calculation
    # -----------------------------------------------------------------------
    # Each expense is split 3 ways.
    # Amit's share  = 1000 + 500 + 300 = 1800
    # Neha's share  = 1000 + 500 + 300 = 1800
    # Rahul's share = 1000 + 500 + 300 = 1800
    expected_share = round(total / 3, 2)  # 1800.00
    balances = calculate_balances(df)

    for person in ["Amit", "Neha", "Rahul"]:
        row = balances[balances["person"] == person].iloc[0]
        assert abs(row["total_share"] - expected_share) < 0.01, (
            f"Test 1 FAILED: {person}'s share should be {expected_share} "
            f"but got {row['total_share']}"
        )
    print("  [PASS] Test 1: per-person share is correct.")

    # -----------------------------------------------------------------------
    # Test 2: Net balances sum to zero
    # -----------------------------------------------------------------------
    net_sum = round(balances["net_balance"].sum(), 2)
    assert abs(net_sum) < 0.01, (
        f"Test 2 FAILED: sum of net balances should be 0 but got {net_sum}"
    )
    print("  [PASS] Test 2: net balances sum to zero.")

    # -----------------------------------------------------------------------
    # Test 3: Settlements clear all outstanding balances
    # -----------------------------------------------------------------------
    settlements = calculate_settlements(balances)

    # Apply settlements to balance dict and verify everything reaches ~0
    check = balances.set_index("person")["net_balance"].to_dict()
    for txn in settlements:
        check[txn["from"]] = round(check[txn["from"]] + txn["amount"], 2)
        check[txn["to"]] = round(check[txn["to"]] - txn["amount"], 2)

    for person, remaining in check.items():
        assert abs(remaining) < 0.01, (
            f"Test 3 FAILED: {person} still has balance ₹{remaining} after settlements."
        )
    print("  [PASS] Test 3: settlements clear all balances.")

    # -----------------------------------------------------------------------
    # Test 4: Edge case — one person pays for everyone
    # -----------------------------------------------------------------------
    edge_data = {
        "date":         ["2025-07-01"],
        "description":  ["Full payment"],
        "category":     ["Other"],
        "amount":       [900.00],
        "paid_by":      ["Amit"],
        "split_between":["Amit|Neha|Rahul"],
    }
    edge_df = pd.DataFrame(edge_data)
    edge_balances = calculate_balances(edge_df)

    # Amit paid 900, share = 300 → net = +600
    amit_row = edge_balances[edge_balances["person"] == "Amit"].iloc[0]
    assert abs(amit_row["net_balance"] - 600.0) < 0.01, (
        f"Test 4 FAILED: Amit's net should be 600 but got {amit_row['net_balance']}"
    )
    # Neha paid 0, share = 300 → net = -300
    neha_row = edge_balances[edge_balances["person"] == "Neha"].iloc[0]
    assert abs(neha_row["net_balance"] - (-300.0)) < 0.01, (
        f"Test 4 FAILED: Neha's net should be -300 but got {neha_row['net_balance']}"
    )
    print("  [PASS] Test 4: edge case (one payer) is handled correctly.")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\nAll tests passed.")


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Streamlit also executes the script as __main__.
    if "--test" in sys.argv:
        run_tests()
    else:
        main()
