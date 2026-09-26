"""
One snapshot of the OpenRouter API market, for the price-dispersion panel.
Stdlib only, so it runs from launchd without any environment setup.

Writes  $PANEL_ROOT/snapshots/<UTC timestamp>/   (PANEL_ROOT defaults to ~/openrouter_panel;
        the GitHub Actions copy sets it to the repo folder)
  models.csv.gz          every model: id, slug, HF id, created, list prices, context
  endpoints.csv.gz       every provider endpoint of every paid model (OFFICIAL API):
                         provider, tag (tier/region), prices, quantization, context, uptime
  endpoint_stats.csv.gz  per-provider speed, latency, 30-min request count, data policy,
                         moderation, HQ (website's INTERNAL stats endpoint; unofficial)
Requests are spaced out; a lock file prevents overlapping runs.
"""
import csv, gzip, json, os, sys, time, datetime, urllib.request, urllib.error

def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

ROOT = os.path.expanduser(os.environ.get("PANEL_ROOT", "~/openrouter_panel"))
UA = {"User-Agent": "Mozilla/5.0 (academic research script)"}
SLEEP_OFFICIAL, SLEEP_INTERNAL = 0.35, 0.6
LOCK = os.path.join(ROOT, ".lock")


def get(url, tries=4):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(3 * 2 ** i); continue
            return None
        except Exception:
            if i < tries - 1:
                time.sleep(3 * 2 ** i); continue
            return None


def write(path, rows):
    if not rows:
        return
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def main():
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 3 * 3600:
        print("another run in progress; exiting"); return
    open(LOCK, "w").write(str(os.getpid()))
    try:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        out = os.path.join(ROOT, "snapshots", ts); os.makedirs(out, exist_ok=True)
        t0 = time.time()

        data = (get("https://openrouter.ai/api/v1/models") or {}).get("data", [])
        models = [dict(id=m["id"], slug=m.get("canonical_slug"), hf=m.get("hugging_face_id"),
                       created=m.get("created"), p_in=m["pricing"].get("prompt"),
                       p_out=m["pricing"].get("completion"), ctx=m.get("context_length")) for m in data]
        write(os.path.join(out, "models.csv.gz"), models)
        paid = [m for m in data if ":free" not in m["id"] and float(m["pricing"].get("completion") or 0) > 0]

        eps, providers_per_model = [], {}
        for m in paid:
            d = get(f"https://openrouter.ai/api/v1/models/{m['id']}/endpoints")
            for e in ((d or {}).get("data") or {}).get("endpoints", []):
                eps.append(dict(snapshot=ts, fetched_at=now(), model=m["id"], provider=e.get("provider_name"), tag=e.get("tag"),
                                p_in=e["pricing"].get("prompt"), p_out=e["pricing"].get("completion"),
                                discount=e["pricing"].get("discount"), quant=e.get("quantization"),
                                ctx=e.get("context_length"), max_out=e.get("max_completion_tokens"),
                                status=e.get("status"), uptime_30m=e.get("uptime_last_30m"),
                                uptime_1d=e.get("uptime_last_1d"),
                                open_weights=bool(m.get("hugging_face_id"))))
                providers_per_model.setdefault(m["id"], set()).add(e.get("provider_name"))
            time.sleep(SLEEP_OFFICIAL)
        write(os.path.join(out, "endpoints.csv.gz"), eps)

        slug = {m["id"]: m.get("canonical_slug") or m["id"] for m in data}
        stats = []
        for mid, provs in providers_per_model.items():
            if len(provs) < 2:
                continue
            d = get(f"https://openrouter.ai/api/frontend/v1/stats/endpoint?permaslug={slug[mid]}&variant=standard")
            x = (d or {}).get("data", d) if d else None
            rows = x if isinstance(x, list) else next((v for v in (x or {}).values() if isinstance(v, list)), []) if isinstance(x, dict) else []
            for r in rows:
                st = r.get("stats") or {}; dp = r.get("data_policy") or {}; pi = r.get("provider_info") or {}
                stats.append(dict(snapshot=ts, fetched_at=now(), model=mid, provider=r.get("provider_name"), tag=r.get("tag") or r.get("name"),
                                  p50_latency=st.get("p50_latency"), p90_latency=st.get("p90_latency"),
                                  p50_throughput=st.get("p50_throughput"), p90_throughput=st.get("p90_throughput"),
                                  requests=st.get("request_count"), window_min=st.get("window_minutes"),
                                  retains_prompts=dp.get("retainsPrompts"), trains=dp.get("training"),
                                  moderation=r.get("moderation_required"), hq=pi.get("headquarters")))
            time.sleep(SLEEP_INTERNAL)
        write(os.path.join(out, "endpoint_stats.csv.gz"), stats)

        print(f"{ts} (finished {now()}): {len(models)} models, {len(eps)} endpoints, {len(stats)} stats rows, {time.time()-t0:.0f}s")
        if not models or not eps:
            sys.exit("snapshot came back empty (OpenRouter unreachable or blocked)")  # non-zero exit -> GitHub emails a failure
    finally:
        try: os.remove(LOCK)
        except OSError: pass


if __name__ == "__main__":
    main()
