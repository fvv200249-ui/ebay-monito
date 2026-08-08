import os
import json
import time
import datetime
import requests

# --- Налаштування пошуку ---
SELLERS = ["vipoutlet", "cdrnwx"]

CATEGORY_ID = "9355"  # Cell Phones & Smartphones
KEYWORDS = "iphone"
TARGET_MODELS = ["12", "13", "14", "15", "16"] 

CHECK_INTERVAL_SECONDS = 150  # 2.5 хв

STATE_FILE = "seen_items.json"
STATE_VERSION = 9  # v9 = Видалив BinConfirm, додав фільтр відгуків продавців (< 10), додав відсоток в ТГ

EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# -------------------- ЛОГІКА ДОПОМІЖНИХ ФУНКЦІЙ --------------------

def log(msg):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)

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

def fetch_ebay_data(token, sellers_only=True):
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    
    if sellers_only:
        sellers_str = "|".join(SELLERS)
        params = {
            "q": KEYWORDS,
            "category_ids": CATEGORY_ID,
            "filter": f"sellers:{{{sellers_str}}}",
            "sort": "newlyListed",
            "limit": "150", 
        }
    else:
        params = {
            "q": KEYWORDS,
            "category_ids": CATEGORY_ID,
            "sort": "newlyListed",
            "limit": "200", 
        }

    try:
        resp = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers=headers,
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("itemSummaries", [])
    except Exception as e:
        log(f"API Помилка під час виклику. Sellers={sellers_only}: {e}")
        return []

def load_state():
    if not os.path.exists(STATE_FILE): return {}, True
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except: return {}, True
    if isinstance(data, list): return {}, True
    if data.get("_version") != STATE_VERSION: return data.get("active", {}), True
    return data.get("active", {}), False

def save_state(active):
    with open(STATE_FILE, "w") as f:
        json.dump({"_version": STATE_VERSION, "active": active}, f)

def send_telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
    except Exception as e:
        log(f"Не вдалось надіслати повідомлення в Telegram: {e}")

# -------------------- БЛОКИ ПЕРЕВІРКИ АЙФОНІВ ТА МАТЕМАТИКА --------------------

def is_icloud_locked(title):
    t = title.lower()
    exclude_words = ["icloud", "activation lock", "ic lock", "account lock"]
    return any(w in t for w in exclude_words)

def check_target_sellers(title):
    t = title.lower()
    return any(f"iphone {m}" in t for m in TARGET_MODELS)

def get_global_sniper_limit(item):
    t = item.get("title", "").lower()
    cond_id = str(item.get("conditionId", ""))
    is_new = (cond_id == "1000" or "brand new" in t)
    
    if "16 plus" in t: return 325
    if "16 pro max" in t: return 0   
    if "16 pro" in t: return 0 
    if "16" in t: return 300
    
    if "15 pro max" in t: return 300
    if "15 pro" in t: return 270
    if "15 plus" in t: return 240
    if "15" in t: return 240
    
    if "14 pro max" in t: return 260
    if "14 pro" in t: return 250
    if "14 plus" in t: return 160
    if "14" in t: return 160
    
    if "13 pro max" in t: return 0 
    if "13 pro" in t: return 0 
    if "13 mini" in t: return 0 
    if "13" in t: return (175 if is_new else 160)
    
    if "12 pro max" in t: return 170
    if "12 pro" in t: return 0
    if "12 mini" in t: return 0
    if "12" in t: return 105
    
    return 0

# -------------------- ГОЛОВНИЙ WORKER --------------------

def run_check():
    token = get_token()
    
    target_data = fetch_ebay_data(token, sellers_only=True)
    global_data = fetch_ebay_data(token, sellers_only=False)

    all_raw_items = { item.get("itemId") : item for item in (target_data + global_data) if item.get("itemId") }

    previous_active, is_migration = load_state()
    current_active = {}
    
    new_alerts = []
    price_change_alerts = []

    for item_id, item in all_raw_items.items():
        title = item.get("title", "")
        
        try: price = float(item.get("price", {}).get("value"))
        except: continue
            
        if is_icloud_locked(title): 
            continue 
            
        seller_info = item.get("seller", {})
        seller_username = str(seller_info.get("username", "")).lower()
        
        # Перевірка рейтингу продавця (ФІЛЬТР ШАХРАЇВ)
        try: 
            feedback_score = int(seller_info.get("feedbackScore", 0))
        except (ValueError, TypeError): 
            feedback_score = 0
            
        if feedback_score < 10:
            continue
        
        is_targeted = False
        if seller_username in [s.lower() for s in SELLERS] and check_target_sellers(title):
            is_targeted = True

        global_threshold = get_global_sniper_limit(item)
        is_sniper_deal = (global_threshold > 0 and price <= global_threshold)
        
        if not is_targeted and not is_sniper_deal:
            continue
            
        if is_targeted and is_sniper_deal: 
            alert_header = "🚨🎯 ШАРА НА АКАУНТІ" 
        elif is_targeted: 
            alert_header = "🎯 ВІД ПЕРЕВІРЕНОГО"
        else:
            alert_header = "🚨 ГЛОБАЛЬНИЙ СНІПІНГ"

        current_active[item_id] = price
        if is_migration: 
            continue 

        old_price = previous_active.get(item_id)
        if old_price is None:
            new_alerts.append( (item, alert_header, feedback_score) )
        elif price != old_price:
            price_change_alerts.append( (item, old_price, price, alert_header, feedback_score) )

    # ОПОВІЩЕННЯ ТЕЛЕГРАМ (Без небезпечних чекаутів!)
    for item, header, f_score in new_alerts:
        p_val = item.get("price", {}).get("value", "?")
        cur = item.get("price", {}).get("currency", "")
        
        seller = item.get("seller", {}).get("username", "Unknown")
        f_percent = item.get("seller", {}).get("feedbackPercentage", "?")
        
        msg = (f"{header}\n"
               f"🆕 {seller} (Рейтинг: {f_score} | ⭐ {f_percent}%)\n\n"
               f"📌 {item.get('title')}\n"
               f"💰 Ціна: {p_val} {cur}\n\n"
               f"🛒 Сторінка лота:\n{item.get('itemWebUrl', '')}")
        send_telegram(msg)
        
    for item, old_p, new_p, header, f_score in price_change_alerts:
        cur = item.get("price", {}).get("currency", "")
        
        seller = item.get("seller", {}).get("username", "Unknown")
        f_percent = item.get("seller", {}).get("feedbackPercentage", "?")
        
        icon = "📉" if new_p < old_p else "📈"
        text_d = "ЗНИЖКА" if new_p < old_p else "ЗДОРЖ."
        
        msg = (f"{header}\n"
               f"{icon} {text_d}: {seller} (Рейтинг: {f_score} | ⭐ {f_percent}%)\n\n"
               f"📌 {item.get('title')}\n"
               f"💰 Було: {old_p} -> {new_p} {cur}\n\n"
               f"🛒 Сторінка лота:\n{item.get('itemWebUrl', '')}")
        send_telegram(msg)
        
    save_state(current_active)

    if is_migration:
        log(f"[DB:Migration] Укріпили базу v{STATE_VERSION}. Впроваджено фільтр антишахраїв. (Спостерігаємо: {len(current_active)} шт).")
    else:
        log(f"Опитано лоти. Знахідок нових: {len(new_alerts)}, Змін цін: {len(price_change_alerts)}.")


def main():
    log(f"Запуск V9! BinConfirm викинуто. Фільтр рейтингу < 10 ввімкнено. Безпечний сніпінг.")
    while True:
        try:
            run_check()
        except Exception as e:
            log(f"Помилка основного циклу. Чекаємо реконект: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
