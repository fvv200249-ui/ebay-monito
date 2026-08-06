import os
import json
import time
import requests

SELLER = "vipoutlet"
CATEGORY_ID = "9355"  
KEYWORDS = "iphone"
MODELS = ["iphone 12", "iphone 13", "iphone 14", "iphone 15"]
STORAGES = ["128", "256"] 

STATE_FILE = "seen_items.json"
STATE_VERSION = 4 

EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

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
        "limit": "200", 
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

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}, True

    with open(STATE_FILE) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {}, True

    if isinstance(data, list):
        return {}, True

    if data.get("_version") != STATE_VERSION:
        return data.get("active", {}), True

    return data.get("active", {}), False

def save_state(active):
    with open(STATE_FILE, "w") as f:
        json.dump({"_version": STATE_VERSION, "active": active}, f)

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

def run_monitor():
    try:
        token = get_token()
        items = search_items(token)

        previous_active, is_migration = load_state()
        current_active = {} 
        new_or_restocked = []
        price_changes = []

        for item in items:
            item_id = item.get("itemId")
            title = item.get("title", "")
            if not item_id or not matches_filters(title):
                continue

            price_info = item.get("price", {})
            try:
                price = float(price_info.get("value"))
            except (TypeError, ValueError):
                price = None

            current_active[item_id] = price

            if is_migration:
                continue

            if item_id not in previous_active:
                new_or_restocked.append(item)
            else:
                old_price = previous_active[item_id]
                if old_price is not None and price is not None and price != old_price:
                    price_changes.append((item, old_price, price))

        for item in new_or_restocked:
            price = item.get("price", {})
            price_str = f"{price.get('value', '?')} {price.get('currency', '')}"
            url = item.get("itemWebUrl", "")
            text = f"🆕 Поповнення або Новий лот!\n{item.get('title')}\n💰 {price_str}\n{url}"
            send_telegram(text)

        for item, old_price, new_price in price_changes:
            currency = item.get("price", {}).get("currency", "")
            url = item.get("itemWebUrl", "")
            icon = "📉" if new_price < old_price else "📈"
            label = "Знижена ціна" if new_price < old_price else "Підвищена ціна"
            text = (
                f"{icon} {label}: {item.get('title')}\n"
                f"💰 {old_price} → {new_price} {currency}\n"
                f"{url}"
            )
            send_telegram(text)

        save_state(current_active)
        print(f"Перевірка успішна. Знайдено лотів: {len(items)}, поповнень: {len(new_or_restocked)}.")
    except Exception as e:
        print(f"Помилка в циклі моніторингу: {e}")

if __name__ == "__main__":
    print("Запуск eBay Monitor на Railway...")
    while True:
        run_monitor()
        time.sleep(300)
