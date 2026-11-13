# Indian Corporate Actions Processing Engine

A practice version of what an **Asset Servicing / Corporate Actions** team does every day:
check incoming corporate action events, work out which clients are entitled, process the
events (including client elections and votes), reconcile what we expected against what the
depository actually credited, and push every problem into an exception queue with an owner and a deadline.

> **All data is fake.** The company names (Reliance, Bharti Airtel, BSE, Sun Pharma, Tata Motors)
> are real, but every event, date, ratio, price, client and amount is made up for practice.
> The tax rules are simplified and are not tax advice.

---

## What it covers

| Area | What the engine does |
|---|---|
| **Event validation** | Checks every vendor event before processing: supported type, required fields, **duplicates from two vendors**, positive amounts/ratios, date order, cost split = 100%, stock actually held |
| **Record-date eligibility** | Uses **settled** holdings under **T+1**. A share bought *on* the record date is not eligible; a share sold *on* the record date still is |
| **Mandatory events** | Bonus (1:1, 2:1), cash dividend with **TDS**, demerger with **cost-of-acquisition split** |
| **Voluntary events** | Rights issue (subscribe / renounce / lapse, default lapse), AGM e-voting |
| **Instruction checks** | Over-election, late instruction, instruction from a non-holder, no instruction received |
| **Vote checks** | Over-voting (capped at holding), no vote received |
| **Reconciliation** | Expected vs depository/registrar credits: share shortfalls, missing credits, **wrong TDS rate** |
| **Exception queue** | Reason code, severity, owner team, SLA due date, required action |
| **Controls** | Cost basis preserved, total cost explained, no over-processing, every break raised |
| **Outputs** | 13-sheet Excel report, client notification per event per client, Streamlit dashboard |

---

## The fake scenario

**5 clients**

| Account | Client | Type | Why it is interesting |
|---|---|---|---|
| CLT001 | Priya Sharma | Resident individual | Small dividend - below TDS threshold |
| CLT002 | Arjun Mehta | Resident individual, **no PAN** | Higher TDS rate (20%) |
| CLT003 | Kavya Nair | Non-resident | 20% TDS, no threshold |
| CLT004 | Shakti Growth Mutual Fund | Mutual fund | TDS exempt |
| CLT005 | Indus Traders Pvt Ltd | Company | 10% TDS |

**10 events in the feed (6 good, 4 deliberately bad)**

| Event | Stock | Type | Result |
|---|---|---|---|
| CA-2026-0001 | RELIANCE | 1:1 bonus | Processed |
| CA-2026-0002 | BHARTIARTL | 1:14 rights issue at Rs 1,200 | Processed (with client elections) |
| CA-2026-0003 | BSE | 2:1 bonus | Processed |
| CA-2026-0004 | BSE | Same bonus again from Vendor B | **Flagged - duplicate** |
| CA-2026-0005 | SUNPHARMA | Rs 8 dividend | Processed (with TDS) |
| CA-2026-0006 | SUNPHARMA | AGM e-voting, 3 resolutions | Processed (with client votes) |
| CA-2026-0007 | TATAMOTORS | 1:1 demerger into TMCV, cost split 65/35 | Processed |
| CA-2026-0008 | RELIANCE | Dividend of **-Rs 6** | **Flagged - invalid amount** |
| CA-2026-0009 | INFY | Dividend | **Flagged - no client holds it** |
| CA-2026-0010 | BHARTIARTL | Pay date before record date | **Flagged - date sequence** |

**Problems planted on purpose**

- Trades around record dates to test T+1 eligibility (`data/trades.csv`, column `test_purpose`)
- CLT002 elects 11 rights shares but has only 10 entitlements (150 ÷ 14 = 10.71, fraction dropped)
- CLT004's rights instruction arrives after the client deadline
- CLT005 bought on the record date and still sends an instruction
- CLT003 sends no rights instruction - default lapse
- CLT001 votes 400 shares but holds 200
- Depository credits CLT005 only 150 Reliance bonus shares instead of 300
- Registrar deducts 10% TDS for CLT002 (should be 20%, no PAN) and for the mutual fund (should be 0%)
- CLT003's TMCV demerger shares never arrive

**Run results**

| Metric | Result |
|---|---|
| Events received / processed / flagged | 10 / 6 / 4 |
| Straight-through processing (STP) rate | 60% |
| Expected credits / matched / breaks | 21 / 17 / 4 (81% match rate) |
| Exceptions | 14 (9 High, 3 Medium, 2 Low) |
| Controls | 8 of 8 pass |

---

## How the processing works

```
events_feed.csv
      │
      ▼
1. VALIDATION ────────── bad event ──────────────┐
      │ good events (sorted by record date)        │
      ▼                                            │
2. ELIGIBILITY  apply trades settled by record date│
      │         (T+1) -> who holds what            │
      ▼                                            ▼
3. PROCESSING   bonus / dividend+TDS / demerger    EXCEPTION QUEUE
      │         rights + client elections ──── problem ──▶ (reason code,
      │         AGM + client votes                         severity, owner,
      ▼                                                    SLA due date,
4. RECONCILIATION  expected vs depository_credits ─ break ─▶ action)
      │
      ▼
5. CONTROLS + AUDIT LOG + NOTIFICATIONS + EXCEL + DASHBOARD
```

Key rules, with examples from the data:

- **Bonus** - shares go up, total cost stays the same.
  CLT004 BSE: 1,200 shares → +2,400 bonus = 3,600; cost per share falls from Rs 2,200 to Rs 733.33.
- **Dividend** - cash = shares × rate, minus TDS.
  CLT002 Sun Pharma: 3,000 × Rs 8 = Rs 24,000; no PAN → 20% TDS = Rs 4,800; net Rs 19,200.
- **Demerger** - new shares created; original cost split by the issuer's ratio.
  CLT001: 250 TATAMOTORS (cost Rs 1,75,000) → keeps 250 TATAMOTORS at 65% (Rs 1,13,750) + gets 250 TMCV at 35% (Rs 61,250).
- **Rights** - entitlements = holding ÷ 14, fractions dropped; client chooses; unused rights lapse.
  CLT001: 700 ÷ 14 = 50 rights → subscribes 30 (pays Rs 36,000), renounces 20.
- **Cost control** - opening cost + trades + rights money paid must equal the final book cost exactly.

---

## Project structure

```
india-ca-engine/
├── data/                         <- inputs (edit these to create new scenarios)
│   ├── accounts.csv              clients and tax status
│   ├── securities.csv            stock master
│   ├── opening_positions.csv     holdings on 1-Jan-2026
│   ├── trades.csv                trades around record dates
│   ├── events_feed.csv           vendor corporate action feed
│   ├── client_instructions.csv   rights elections and AGM votes
│   └── depository_credits.csv    what NSDL/CDSL/registrar actually credited
├── ca_engine/
│   ├── config.py                 all business rules: TDS, tolerances, exception catalogue
│   ├── validation.py             step 1 - event scrubbing
│   ├── position_book.py          settled holdings and cost
│   ├── processors.py             step 3 - one function per event type
│   ├── tax.py                    simplified dividend TDS
│   ├── reconciliation.py         step 4 - expected vs received
│   ├── exceptions.py             exception record builder
│   ├── notifications.py          client notices
│   ├── reporting.py              Excel + CSV output
│   └── pipeline.py               runs everything in order + controls + KPIs
├── tests/test_engine.py          24 tests, one per business rule
├── app.py                        Streamlit dashboard
└── run.py                        command-line run
```

---

## How to run

```bash
pip install -r requirements.txt

python run.py               # runs everything, prints a summary, writes outputs/
python -m pytest -q         # runs the 24 tests
streamlit run app.py        # opens the dashboard at http://localhost:8501
```

Outputs:
- `outputs/corporate_actions_report.xlsx` - 13 sheets (Summary, Event_Validation, Eligibility, Entitlements, Instructions, Votes, Cash_Ledger, Reconciliation, Exceptions, Audit_Log, Controls, Opening/Final positions)
- `outputs/notifications/` - one notice per event per client (27 files)
- `outputs/csv/` - every table as CSV

---

## Simplifications (good interview talking points)

- Only weekends are non-business days - a real system loads the NSE holiday calendar.
- Ex-date = record date (true under T+1 in India). Shares are credited at processing time, not on the allotment date.
- TDS: one dividend per company per year assumed for the threshold; surcharge, cess and treaty rates ignored.
- Rights: fully paid shares; renounced entitlements are not valued or sold; fractional entitlements are simply dropped.
- Bonus cost is spread across all shares (portfolio view). For Indian tax, bonus shares have a nil cost of acquisition.
- No fixed income events in this version.

## Possible extensions

Fixed income coupons and redemptions · partly-paid rights and call money · SLA breach ageing · ISO 15022
MT564/MT565/MT566 message parsing · loading real events from NSE · NSE holiday calendar · database storage.

---

## Credit

Inspired by the design of
[ludmila-abd/corporate-actions-simulator](https://github.com/ludmila-abd/corporate-actions-simulator)
(validation → processing → exception queue → reconciliation → dashboard).
This project is written from scratch for the Indian market and adds record-date settlement eligibility,
multi-client processing, TDS, rights elections, AGM voting, depository reconciliation and client notifications.
