"""
run.py — entry point.
Called by Task Scheduler at 08:30, 09:45, 11:00, 14:00 ET Mon-Fri.
"""

import pytz
from datetime import datetime
from screener import run_screen
from notify import send_signals

EST = pytz.timezone("America/New_York")

if __name__ == "__main__":
    now = datetime.now(EST)
    scan_time = now.strftime("%b %d  %I:%M %p ET")

    print(f"\n{'='*50}")
    print(f"NEXUS Screener  {scan_time}")
    print(f"{'='*50}")

    signals = run_screen()

    print(f"\n{'='*50}")
    print(f"Results: {len(signals)} signal(s)")
    for s in signals:
        print(f"  {s['symbol']:6s}  entry=${s['entry']:.2f}  "
              f"stop=${s['stop']:.2f}  target=${s['target']:.2f}  "
              f"conf={s['confidence']}  {s['strategy']}")
    print(f"{'='*50}\n")

    send_signals(signals, scan_time)
