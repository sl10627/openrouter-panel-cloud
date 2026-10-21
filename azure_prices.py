"""
Daily snapshot of Microsoft Azure's public list prices for AI models (Azure Retail Prices API,
serviceName 'Foundry Models': Azure OpenAI, DeepSeek, Kimi, Grok, Mistral, Llama ... in every region).
Public endpoint, no key. About 40 requests, ~40 s, ~39,000 rows, ~1.3 MB a day.
  -> $PANEL_ROOT/azure/<UTC date>.csv.gz   (one file per day; skipped if today's file exists)
List prices only: no usage, no negotiated discounts.
Run:  python3 azure_prices.py [--force]
"""
import csv, gzip, io, json, os, sys, time, datetime, urllib.parse, urllib.request

ROOT = os.path.expanduser(os.environ.get("PANEL_ROOT", "~/openrouter_panel"))
API = "https://prices.azure.com/api/retail/prices?" + urllib.parse.urlencode({"$filter": "serviceName eq 'Foundry Models'"})
FIELDS = ["fetched_at", "serviceName", "productName", "skuName", "meterName", "armRegionName", "location",
          "unitOfMeasure", "retailPrice", "tierMinimumUnits", "currencyCode", "type",
          "effectiveStartDate", "isPrimaryMeterRegion", "meterId"]          # unitPrice equals retailPrice; sku/product ids dropped
SORT = ["productName", "meterName", "armRegionName", "type", "tierMinimumUnits"]


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception as e:                      # network hiccup or throttling: back off and retry
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    out = os.path.join(ROOT, "azure", f"{now:%Y-%m-%d}.csv.gz")
    if os.path.exists(out) and "--force" not in sys.argv:
        print(f"{out} exists, skipping"); return
    rows, url, pages = [], API, 0
    while url:
        d = get(url)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows += [{"fetched_at": stamp, **{k: x.get(k) for k in FIELDS[1:]}} for x in d.get("Items", [])]
        url, pages = d.get("NextPageLink"), pages + 1
    if not rows:
        sys.exit("Azure price list came back empty")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    rows.sort(key=lambda r: tuple(str(r[k]) for k in SORT))       # stable order compresses better
    with gzip.GzipFile(tmp, "wb", compresslevel=9, mtime=0) as g, io.TextIOWrapper(g, encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    os.replace(tmp, out)
    print(f"{now:%Y-%m-%dT%H%MZ}: {len(rows)} Azure price rows from {pages} pages -> {out}")


if __name__ == "__main__":
    main()
