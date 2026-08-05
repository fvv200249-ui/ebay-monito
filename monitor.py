import os
import json
import requests

# --- Налаштування пошуку (можна міняти під себе) ---
SELLER = "vipoutlet"
CATEGORY_ID = "9355"  # Cell Phones & Smartphones
KEYWORDS = "iphone"
MODELS = ["iphone 12", "iphone 13", "iphone 14", "iphone 15"]
STORAGES = ["128", "256"]  # шукає ці цифри в назві лота (128GB / 128 GB тощо)

STATE_FILE = "seen_items.json"
STATE_VERSION = 2  # v2 = "живий знімок" активних лотів (не історія за весь час)

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


def load_state():
    """
    Повертає (previous_active, is_migration).
    previous_active: словник {item_id: price} — що було в наявності на попередній перевірці.
    is_migration=True означає, що це перехід зі старого формату файлу (або взагалі перший запуск) —
    у цьому прогоні сповіщення не надсилаються, лише зберігається чиста база для порівняння надалі.
    """
    if not os.path.exists(STATE_FILE):
        return {}, True

    with open(STATE_FILE) as f:
        data = json.load(f)

    if isinstance(data, list):
        # найстаріший формат (просто список ID) -> мігруємо
        return {}, True

    if data.get("_version") != STATE_VERSION:
        # стара кумулятивна версія (ID ніколи не "забувались") -> мігруємо на живий знімок
        return {}, True

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


def main():
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
            # або справді новий лот, або лот, що зник і знову з'явився (поповнення/перевиставлення)
            new_or_restocked.append(item)
        else:
            old_price = previous_active[item_id]
            if old_price is not None and price is not None and price != old_price:
                price_changes.append((item, old_price, price))

    for item in new_or_restocked:
        price = item.get("price", {})
        price_str = f"{price.get('value', '?')} {price.get('currency', '')}"
        url = item.get("itemWebUrl", "")
        text = f"🆕 {item.get('title')}\n💰 {price_str}\n{url}"
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

    if is_migration:
        print(
            f"Оновлення бази трекінгу (нова версія): збережено {len(current_active)} "
            f"активних лотів, сповіщення в цьому прогоні не надсилались."
        )
    else:
        print(
            f"Перевірено {len(items)} лотів, нових/поповнених {len(new_or_restocked)}, "
            f"зміна ціни {len(price_changes)}."
        )


if __name__ == "__main__":
    main()
