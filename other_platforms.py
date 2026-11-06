"""
Same models, other marketplaces. Public endpoints only, no key. Stdlib only.

Hourly
  Hugging Face Inference Providers  https://router.huggingface.co/v1/models
    every model x provider: price, status, HF-measured time to first token and throughput
    -> $PANEL_ROOT/hf/<UTC date>.csv.gz                         (~250 rows, 1 request)
  Vercel AI Gateway                  https://ai-gateway.vercel.sh/v1/models/{id}/endpoints
    every language model x provider: prices (incl. cache, discount, peak-hour multiplier),
    status, uptime, latency and throughput over the last hour
    -> $PANEL_ROOT/vercel/<UTC date>.csv.gz                     (~320 requests, ~1-2 min)
Daily (first run of each UTC day)
  Vercel AI Gateway leaderboard export (anonymized usage shares, CC BY 4.0, updated daily)
    models and labs: daily share of tokens, requests, spend; providers: all-time ranking
    -> $PANEL_ROOT/vercel_leaderboard/<UTC date>/<dataset>.json.gz

Each hourly run appends one gzip member per file, as in hourly.py.
Run:  python3 other_platforms.py [hf|vercel|leaderboard ...]   (default: all three, leaderboard once a day)
"""
import csv, gzip, io, json, os, sys, time, datetime, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snapshot import get, ROOT

HF_URL = "https://router.huggingface.co/v1/models"
VERCEL_MODELS = "https://ai-gateway.vercel.sh/v1/models"
VERCEL_ENDPOINTS = "https://ai-gateway.vercel.sh/v1/models/{}/endpoints"
VERCEL_BOARD = "https://vercel.com/api/ai/leaderboard-export?dataset={}&modality=all&format=json"
HF_FIELDS = ["run", "fetched_at", "model", "provider", "status", "p_in", "p_out", "is_free", "context_length",
             "first_token_latency_ms", "throughput", "is_model_author", "supports_tools", "supports_structured_output"]
VC_FIELDS = ["run", "fetched_at", "model", "provider", "name", "status", "p_in", "p_out", "p_cache_read", "discount",
             "peak_multiplier", "peak_windows_utc", "quant", "context_length", "has_zdr", "has_no_training",
             "uptime_15m", "uptime_1h", "uptime_1d", "latency_p50", "latency_p95", "throughput_p50", "throughput_p95"]


def stamp():
    t = datetime.datetime.now(datetime.timezone.utc)
    return t, t.strftime("%Y-%m-%dT%H%MZ"), t.strftime("%Y-%m-%dT%H:%M:%SZ")


def append(folder, day, rows, fields):
    if not rows:
        return
    os.makedirs(os.path.join(ROOT, folder), exist_ok=True)
    path = os.path.join(ROOT, folder, f"{day}.csv.gz")
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=fields)
    if not os.path.exists(path):
        w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "at", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def per_million(x):
    """Vercel quotes dollars per token as strings; HF quotes dollars per million tokens."""
    try:
        return round(float(x) * 1e6, 6)
    except (TypeError, ValueError):
        return None


def hf():
    t, run, ts = stamp()
    d = get(HF_URL)
    if not d:
        print("Hugging Face fetch failed"); return 0
    rows = []
    for m in d.get("data", []):
        for p in m.get("providers", []):
            pr = p.get("pricing") or {}
            rows.append({"run": run, "fetched_at": ts, "model": m.get("id"), "provider": p.get("provider"),
                         "status": p.get("status"), "p_in": pr.get("input"), "p_out": pr.get("output"),
                         "is_free": p.get("is_free"), "context_length": p.get("context_length"),
                         "first_token_latency_ms": p.get("first_token_latency_ms"), "throughput": p.get("throughput"),
                         "is_model_author": p.get("is_model_author"), "supports_tools": p.get("supports_tools"),
                         "supports_structured_output": p.get("supports_structured_output")})
    append("hf", t.strftime("%Y-%m-%d"), rows, HF_FIELDS)
    print(f"{run}: {len(rows)} Hugging Face provider rows")
    return len(rows)


def vercel():
    t, run, ts = stamp()
    d = get(VERCEL_MODELS)
    if not d:
        print("Vercel model list failed"); return 0
    ids = [m["id"] for m in d.get("data", []) if m.get("type") == "language"]
    rows, failed = [], 0
    for mid in ids:
        e = get(VERCEL_ENDPOINTS.format(urllib.parse.quote(mid, safe="/")))
        time.sleep(0.15)
        if not e:
            failed += 1; continue
        for x in (e.get("data") or {}).get("endpoints", []):
            pr, pk = x.get("pricing") or {}, (x.get("pricing") or {}).get("peak_pricing") or {}
            lat, thr = x.get("latency_last_1h") or {}, x.get("throughput_last_1h") or {}
            rows.append({"run": run, "fetched_at": ts, "model": mid, "provider": x.get("provider_name"), "name": x.get("name"),
                         "status": x.get("status"), "p_in": per_million(pr.get("prompt")), "p_out": per_million(pr.get("completion")),
                         "p_cache_read": per_million(pr.get("input_cache_read")), "discount": pr.get("discount"),
                         "peak_multiplier": pk.get("multiplier"), "peak_windows_utc": json.dumps(pk.get("windows")) if pk else "",
                         "quant": x.get("quantization"), "context_length": x.get("context_length"),
                         "has_zdr": x.get("has_zdr"), "has_no_training": x.get("has_no_training"),
                         "uptime_15m": x.get("uptime_last_15m"), "uptime_1h": x.get("uptime_last_1h"), "uptime_1d": x.get("uptime_last_1d"),
                         "latency_p50": lat.get("p50"), "latency_p95": lat.get("p95"),
                         "throughput_p50": thr.get("p50"), "throughput_p95": thr.get("p95")})
    append("vercel", t.strftime("%Y-%m-%d"), rows, VC_FIELDS)
    print(f"{run}: {len(rows)} Vercel endpoint rows from {len(ids) - failed}/{len(ids)} language models")
    return len(rows)


def leaderboard(force=False):
    t, run, ts = stamp()
    folder = os.path.join(ROOT, "vercel_leaderboard", t.strftime("%Y-%m-%d"))
    if os.path.isdir(folder) and not force:
        print(f"{folder} exists, skipping"); return 0
    os.makedirs(folder, exist_ok=True)
    n = 0
    for ds in ("models", "labs", "providers"):
        d = get(VERCEL_BOARD.format(ds))
        if not d:
            print(f"Vercel leaderboard {ds} failed"); continue
        with gzip.GzipFile(os.path.join(folder, f"{ds}.json.gz"), "wb", mtime=0) as g:
            g.write(json.dumps({"fetched_at": ts, **d}).encode())
        n += len(d.get("rows", []))
    print(f"{run}: {n} Vercel leaderboard rows -> {folder}")
    return n


if __name__ == "__main__":
    jobs = sys.argv[1:] or ["hf", "vercel", "leaderboard"]
    for j in jobs:
        try:
            {"hf": hf, "vercel": vercel, "leaderboard": leaderboard}[j]()
        except Exception as e:                       # one source failing must not stop the others
            print(f"{j} failed: {e!r}")
