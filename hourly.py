"""
Hourly watch of every model sold by two or more providers, plus the fixed list in watchlist.txt.
The multi-provider set is re-read each run from the latest full snapshot, so new models join
automatically (watchlist.txt keeps the original 28 models, incl. closed controls, for continuity).
Stdlib only. For every watched model:
  prices  - all provider endpoints from the OFFICIAL API (/api/v1/models/{id}/endpoints)
            -> $PANEL_ROOT/hourly/<UTC date>.csv.gz
  traffic - per-provider 30-min request count, latency, throughput from the website's
            INTERNAL stats endpoint (unofficial; same call the 4x-daily snapshot makes)
            -> $PANEL_ROOT/hourly_stats/<UTC date>.csv.gz
Each run appends one gzip member per file, so the files stay valid while they grow.
About 330 requests, ~4 min.
"""
import csv, glob, gzip, io, os, sys, time, datetime
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


def multi_provider_models(min_rows=1000):
    """Paid models with 2+ providers in the latest snapshot that has at least min_rows endpoints."""
    for path in sorted(glob.glob(os.path.join(ROOT, "snapshots", "*", "endpoints.csv.gz")), reverse=True):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if len(rows) < min_rows:
            continue
        sellers = {}
        for r in rows:
            try:
                paid = float(r["p_out"] or 0) > 0
            except ValueError:
                paid = False
            if paid:
                sellers.setdefault(r["model"], set()).add(r["provider"])
        return sorted(m for m, s in sellers.items() if len(s) >= 2)
    return []


def main():
    fixed = [l.strip() for l in open(os.path.join(HERE, "watchlist.txt")) if l.strip() and not l.startswith("#")]
    watch = fixed + [m for m in multi_provider_models() if m not in fixed]
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
