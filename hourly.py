"""
Hourly price watch for the endpoints that change price (time-of-day / weekday pricing).
Stdlib only. For every model in watchlist.txt, fetches all provider endpoints from the
OFFICIAL API (/api/v1/models/{id}/endpoints) and appends them to
  $PANEL_ROOT/hourly/<UTC date>.csv.gz
(one gzip member per run, so the file stays valid while it grows). About 30 requests, ~15 s.
"""
import csv, gzip, io, os, sys, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snapshot import get, now, ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = ["run", "fetched_at", "model", "provider", "tag", "p_in", "p_out", "discount", "quant", "status"]


def main():
    watch = [l.strip() for l in open(os.path.join(HERE, "watchlist.txt")) if l.strip() and not l.startswith("#")]
    run = datetime.datetime.now(datetime.timezone.utc)
    rows, missing = [], []
    for mid in watch:
        d = get(f"https://openrouter.ai/api/v1/models/{mid}/endpoints", tries=3)
        eps = ((d or {}).get("data") or {}).get("endpoints", [])
        if not eps:
            missing.append(mid)
        for e in eps:
            rows.append(dict(run=run.strftime("%Y-%m-%dT%H%MZ"), fetched_at=now(), model=mid,
                             provider=e.get("provider_name"), tag=e.get("tag"),
                             p_in=e["pricing"].get("prompt"), p_out=e["pricing"].get("completion"),
                             discount=e["pricing"].get("discount"), quant=e.get("quantization"),
                             status=e.get("status")))
        time.sleep(0.3)
    print(f"{run:%Y-%m-%dT%H%MZ}: {len(rows)} endpoints from {len(watch)-len(missing)}/{len(watch)} models"
          + (f"; no data for {missing}" if missing else ""))
    if not rows:
        sys.exit("hourly watch came back empty (OpenRouter unreachable or blocked)")
    os.makedirs(os.path.join(ROOT, "hourly"), exist_ok=True)
    path = os.path.join(ROOT, "hourly", f"{run:%Y-%m-%d}.csv.gz")
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=FIELDS)
    if not os.path.exists(path):
        w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "at", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


if __name__ == "__main__":
    main()
