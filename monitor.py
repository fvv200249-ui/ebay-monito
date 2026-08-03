import os
import json
import requests

# --- Налаштування пошуку (можна міняти під себе) ---
SELLER = "vipoutlet"
CATEGORY_ID = "9355"  # Cell Phones & Smartphones
KEYWORDS = "iphone"
MODELS = ["iphone 12", "iphone 13", "iphone 14", "iphone 15"]
STORAGES = ["128", "256"]  # шукає ці цифри в назві лота (128GB / 128 GB тощо)

SEEN_FILE = "seen_items.json"

EBAY_CLIENT_ID = os.environ["EBAY_CLIENT_ID"]
EBAY_CLIENT_SECRET = os.environ["EBAY_CLIENT_SECRET"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_token():
    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_items(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    params = {
        "q": KEYWORDS,
        "category_ids": CATEGORY_ID,
        "filter": f"sellers:{{{SELLER}}}",
        "sort": "newlyListed",
        "limit": "50",
    }
    resp = requests.get(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        headers=headers,
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("itemSummaries", [])


def matches_filters(title):
    t = title.lower()
    return any(m in t for m in MODELS) and any(s in t for s in STORAGES)


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f)


def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=20,
    )


def main():
    token = get_token()
    items = search_items(token)

    first_run = not os.path.exists(SEEN_FILE)
    seen = load_seen()
    new_seen = set(seen)
    new_items = []

    for item in items:
        item_id = item.get("itemId")
        title = item.get("title", "")
        if not item_id or item_id in seen:
            continue
        if not matches_filters(title):
            continue
        new_seen.add(item_id)
        if not first_run:
            new_items.append(item)

    for item in new_items:
        price = item.get("price", {})
        price_str = f"{price.get('value', '?')} {price.get('currency', '')}"
        url = item.get("itemWebUrl", "")
        text = f"🆕 {item.get('title')}\n💰 {price_str}\n{url}"
        send_telegram(text)

    save_seen(new_seen)

    if first_run:
        print(f"Перший запуск: збережено {len(new_seen)} існуючих лотів як базу, сповіщення не надсилались.")
    else:
        print(f"Перевірено {len(items)} лотів, нових {len(new_items)}, надіслано сповіщень {len(new_items)}.")


if __name__ == "__main__":
    main()
