"""
Run the whole corporate actions process and print a summary.

    python run.py
"""

from pathlib import Path

from ca_engine import run_pipeline

HERE = Path(__file__).parent


def main():
    results = run_pipeline(HERE / "data", HERE / "outputs")

    print("=" * 70)
    print("INDIAN CORPORATE ACTIONS ENGINE - RUN SUMMARY (fake practice data)")
    print("=" * 70)
    for _, row in results["kpis"].iterrows():
        print(f"{row['metric']:<45}{row['value']:>20}")

    print("\nEVENT VALIDATION")
    print(results["validation"][["event_id", "ticker", "event_type", "processing_status", "reason_code"]]
          .to_string(index=False))

    print("\nCONTROLS")
    print(results["controls"][["control", "result"]].to_string(index=False))

    print("\nEXCEPTION QUEUE")
    print(results["exceptions"][["exception_id", "severity", "reason_code", "event_id", "account_id", "owner"]]
          .to_string(index=False))

    print(f"\nExcel report:   {results['report_path']}")
    print(f"Notifications:  {HERE / 'outputs' / 'notifications'} ({len(results['notifications'])} files)")
    print("Dashboard:      streamlit run app.py")


if __name__ == "__main__":
    main()
