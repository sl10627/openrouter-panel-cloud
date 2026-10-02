"""
Hourly watch of the endpoints that change price during the day (time-of-day / weekday pricing).
Stdlib only. For every model in watchlist.txt:
  prices  - all provider endpoints from the OFFICIAL API (/api/v1/models/{id}/endpoints)
            -> $PANEL_ROOT/hourly/<UTC date>.csv.gz
  traffic - per-provider 30-min request count, latency, throughput from the website's
            INTERNAL stats endpoint (unofficial; same call the 4x-daily snapshot makes)
            -> $PANEL_ROOT/hourly_stats/<UTC date>.csv.gz
Each run appends one gzip member per file, so the files stay valid while they grow.
About 60 requests, ~1 min.
"""
import csv, gzip, io, os, sys, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snapshot import get, now, stats_rows, ROOT, SLEEP_INTERNAL

HERE = os.path.dirname(os.path.abspath(__file__))
PRICE_FIELDS = ["run", "fetched_at", "model", "provider", "tag", "p_in", "p_out", "discount", "quant", "status"]


def append(folder, day, rows, fields):
    os.makedirs(os.path.join(ROOT, folder), exist_ok=True)
    path = os.path.join(ROOT, folder, f"{day}.csv.gz")
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=fields)
    if not os.path.exists(path):
        w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "at", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def main():
    watch = [l.strip() for l in open(os.path.join(HERE, "watchlist.txt")) if l.strip() and not l.startswith("#")]
    run = datetime.datetime.now(datetime.timezone.utc)
    tag = run.strftime("%Y-%m-%dT%H%MZ")

    rows, missing = [], []
    for mid in watch:
        d = get(f"https://openrouter.ai/api/v1/models/{mid}/endpoints", tries=3)
        eps = ((d or {}).get("data") or {}).get("endpoints", [])
        if not eps:
            missing.append(mid)
        for e in eps:
            rows.append(dict(run=tag, fetched_at=now(), model=mid,
                             provider=e.get("provider_name"), tag=e.get("tag"),
                             p_in=e["pricing"].get("prompt"), p_out=e["pricing"].get("completion"),
                             discount=e["pricing"].get("discount"), quant=e.get("quantization"),
                             status=e.get("status")))
        time.sleep(0.3)

    slugs = {m["id"]: m.get("canonical_slug") or m["id"]
             for m in (get("https://openrouter.ai/api/v1/models", tries=3) or {}).get("data", [])}
    stats = []
    for mid in watch:
        if mid in slugs:
            stats += [{"run": r.pop("snapshot"), **r} for r in stats_rows(mid, slugs[mid], tag)]
        time.sleep(SLEEP_INTERNAL)

    print(f"{tag}: {len(rows)} endpoints from {len(watch)-len(missing)}/{len(watch)} models, {len(stats)} stats rows"
          + (f"; no prices for {missing}" if missing else ""))
    if not rows:
        sys.exit("hourly watch came back empty (OpenRouter unreachable or blocked)")
    append("hourly", f"{run:%Y-%m-%d}", rows, PRICE_FIELDS)
    if stats:
        append("hourly_stats", f"{run:%Y-%m-%d}", stats, list(stats[0].keys()))


if __name__ == "__main__":
    main()
