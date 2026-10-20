import os
import json
import time
import base64
import statistics
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

# Required GitHub Actions secrets:
# EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, DISCORD_WEBHOOK_URL
EBAY_CLIENT_ID = os.environ["EBAY_CLIENT_ID"]
EBAY_CLIENT_SECRET = os.environ["EBAY_CLIENT_SECRET"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

MAX_PRICE_USD = float(os.getenv("MAX_PRICE_USD", "100"))
MIN_DISCOUNT_PERCENT = float(os.getenv("MIN_DISCOUNT_PERCENT", "25"))
MAX_ALERTS_PER_RUN = int(os.getenv("MAX_ALERTS_PER_RUN", "8"))
MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
STATE_FILE = "seen_items.json"

SEARCHES = {
    "GPU": [
        "GTX 1650 graphics card", "GTX 1660 graphics card",
        "GTX 1070 graphics card", "RTX 2060 graphics card",
        "RTX 3060 graphics card", "RX 6600 graphics card",
    ],
    "DDR4 RAM": ["16GB DDR4 RAM kit 2x8", "32GB DDR4 RAM kit 2x16"],
    "DDR5 RAM": ["16GB DDR5 RAM kit 2x8", "32GB DDR5 RAM kit 2x16"],
    "CPU": [
        "Ryzen 5 3600 CPU", "Ryzen 5 5600 CPU",
        "Intel Core i5-10400 CPU", "Intel Core i5-12400 CPU",
    ],
    "Motherboard": [
        "B450 AM4 motherboard", "B550 AM4 motherboard",
        "B660 LGA1700 motherboard", "B760 LGA1700 motherboard",
    ],
    "PC Case": ["ATX PC case", "Micro ATX PC case"],
}

EXCLUDE_TERMS = [
    "for parts", "not working", "broken", "damaged", "repair",
    "empty box", "box only", "manual only", "fan only", "heatsink only",
    "waterblock only", "read description", "untested",
]

def api_json(url, method="GET", headers=None, data=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {exc.code}: {detail[:400]}") from exc

def get_ebay_token():
    auth = base64.b64encode(
        f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()
    ).decode()
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }).encode()
    result = api_json(
        "https://api.ebay.com/identity/v1/oauth2/token",
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=body,
    )
    return result["access_token"]

def load_seen():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_seen(seen):
    # Bound repository-state size.
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-5000:], f)

def ebay_search(token, query):
    params = urllib.parse.urlencode({
        "q": query,
        "limit": "50",
        "sort": "price",
        "filter": "buyingOptions:{FIXED_PRICE|AUCTION}",
    })
    return api_json(
        "https://api.ebay.com/buy/browse/v1/item_summary/search?" + params,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID,
            "Accept": "application/json",
        },
    ).get("itemSummaries", [])

def price_parts(item):
    price = float(item.get("price", {}).get("value", "0"))
    shipping = 0.0
    options = item.get("shippingOptions") or []
    if options:
        value = (options[0].get("shippingCost") or {}).get("value")
        if value is not None:
            shipping = float(value)
    return price, shipping, price + shipping

def excluded(title):
    title = title.lower()
    return any(term in title for term in EXCLUDE_TERMS)

def send_discord(message):
    body = json.dumps({"content": message[:1900]}).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord webhook returned {response.status}")

def main():
    token = get_ebay_token()
    seen = load_seen()
    updated_seen = set(seen)
    candidates = []

    print("Starting eBay scan:", datetime.now(timezone.utc).isoformat())

    for category, queries in SEARCHES.items():
        for query in queries:
            try:
                items = ebay_search(token, query)
            except Exception as exc:
                print(f"Search error for {query!r}: {exc}")
                continue

            # Rough comparison only: median of active search results.
            # These results may include different conditions/configurations.
            comparable_totals = []
            for item in items:
                if excluded(item.get("title", "")):
                    continue
                try:
                    _, _, total = price_parts(item)
                    if total > 0:
                        comparable_totals.append(total)
                except (TypeError, ValueError):
                    pass
            reference = statistics.median(comparable_totals) if len(comparable_totals) >= 8 else None

            for item in items:
                item_id = item.get("itemId")
                title = item.get("title", "Untitled listing")
                url = item.get("itemWebUrl")
                if not item_id or item_id in seen or not url or excluded(title):
                    continue
                try:
                    price, shipping, total = price_parts(item)
                except (TypeError, ValueError):
                    continue
                if total <= 0 or total > MAX_PRICE_USD:
                    continue
                # Avoid making a deal claim without enough comparison results.
                if reference is None or reference <= 0:
                    continue
                discount = (reference - total) / reference * 100
                if discount < MIN_DISCOUNT_PERCENT:
                    continue

                candidates.append({
                    "id": item_id, "category": category, "query": query,
                    "title": title, "url": url, "price": price,
                    "shipping": shipping, "total": total,
                    "reference": reference, "discount": discount,
                    "condition": item.get("condition", "Not specified"),
                })
                updated_seen.add(item_id)
            time.sleep(0.2)

    candidates.sort(key=lambda item: item["discount"], reverse=True)
    chosen = candidates[:MAX_ALERTS_PER_RUN]

    if not chosen:
        print("No new listings passed the current filters.")

    for item in chosen:
        message = (
            f"🧩 **Potential eBay deal — {item['category']}**\n"
            f"**{item['title']}**\n"
            f"Price: ${item['price']:.2f} + shipping ${item['shipping']:.2f} "
            f"= **${item['total']:.2f before tax**\n"
            f"Condition: {item['condition']}\n"
            f"Active-result median: ~${item['reference']:.2f}; "
            f"{item['discount']:.0f}% below this rough comparison\n"
            f"Search: `{item['query']}`\n{item['url']}\n"
            "⚠️ This is a rough active-listing comparison, not a verified fair value. "
            "Check exact model, condition, shipping, seller feedback, returns, and compatibility."
        )
        try:
            send_discord(message)
            print("Sent alert:", item["title"])
            time.sleep(1.2)
        except Exception as exc:
            print("Discord send failed:", exc)

    save_seen(updated_seen)
    print(f"Scan complete. Alerts sent: {len(chosen)}")

if __name__ == "__main__":
    main()
