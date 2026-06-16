"""
TechStore — бэкенд сервер
Деплой: Render.com (бесплатно, навсегда)
"""

import os, json, csv, io
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

# ============================================================
# КОНФИГУРАЦИЯ
# На Render: Dashboard → ваш сервис → Environment → Add Variable
# ============================================================
BOT_TOKEN    = os.getenv("BOT_TOKEN",   "ВСТАВЬТЕ_НОВЫЙ_ТОКЕН")
ADMIN_ID     = int(os.getenv("ADMIN_ID",    "1398884"))
SHOP_URL     = os.getenv("SHOP_URL",    "https://YOUR-APP.onrender.com")
ADMIN_SECRET = os.getenv("ADMIN_SECRET","secret123")

# ============================================================
# ХРАНИЛИЩЕ (JSON-файлы в папке data/)
# ============================================================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

def load_json(name, default):
    path = f"{DATA_DIR}/{name}.json"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(name, data):
    with open(f"{DATA_DIR}/{name}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ============================================================
# ТОВАРЫ — из products.csv
# ============================================================
def load_products_from_csv():
    path = f"{DATA_DIR}/products.csv"
    if not os.path.exists(path):
        return []
    products = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            products.append({
                "id":       int(row["id"]),
                "name":     row["name"],
                "spec":     row["spec"],
                "cat":      row["cat"],
                "price":    int(row["price"]),
                "oldPrice": int(row["oldPrice"]) if row.get("oldPrice") else None,
                "emoji":    row.get("emoji", "📦"),
                "badge":    row.get("badge") or None,
                "isNew":    row.get("isNew", "").lower() in ("true", "1", "yes"),
                "desc":     row.get("desc", ""),
                "image":    row.get("image") or None,
            })
    return products

# ============================================================
# TELEGRAM
# ============================================================
def tg_send(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception as e:
        print(f"TG error: {e}")

# ============================================================
# PING — чтобы Render не засыпал
# UptimeRobot будет стучать сюда каждые 5 минут
# ============================================================
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "TechStore API работает ✅", "time": datetime.now().strftime("%d.%m.%Y %H:%M")})

# ============================================================
# ТОВАРЫ
# ============================================================
@app.route("/api/products", methods=["GET"])
def get_products():
    return jsonify(load_products_from_csv())

@app.route("/api/products/upload-csv", methods=["POST"])
def upload_csv():
    if request.headers.get("X-Admin-Token") != ADMIN_SECRET:
        return jsonify({"error": "Нет доступа"}), 401
    if "file" not in request.files:
        return jsonify({"error": "Файл не найден"}), 400

    content = request.files["file"].read().decode("utf-8")
    reader  = csv.DictReader(io.StringIO(content))
    if not {"id", "name", "price", "cat"}.issubset(set(reader.fieldnames or [])):
        return jsonify({"error": "Нужны колонки: id, name, price, cat"}), 400

    with open(f"{DATA_DIR}/products.csv", "w", encoding="utf-8") as f:
        f.write(content)

    count = sum(1 for _ in csv.DictReader(io.StringIO(content)))
    tg_send(ADMIN_ID, f"✅ Каталог обновлён!\nЗагружено товаров: <b>{count}</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    return jsonify({"ok": True, "count": count})

# ============================================================
# ЗАКАЗЫ
# ============================================================
@app.route("/api/orders", methods=["GET"])
def get_orders():
    if request.headers.get("X-Admin-Token") != ADMIN_SECRET:
        return jsonify({"error": "Нет доступа"}), 401
    return jsonify(load_json("orders", []))

@app.route("/api/orders", methods=["POST"])
def create_order():
    data   = request.json
    orders = load_json("orders", [])
    data["serverDate"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    data["status"]     = "new"
    orders.append(data)
    save_json("orders", orders)

    items  = "\n".join([f"  • {i['name']} × {i['qty']} = {i['price']*i['qty']:,} ₽" for i in data.get("items", [])])
    addr   = f"\n📍 {data['address']}" if data.get("address") else ""
    promo  = f"\n🎁 Промокод: {data['promo']}" if data.get("promo") else ""
    note   = f"\n💬 {data['comment']}" if data.get("comment") else ""
    mode   = "🚚 Доставка" if data.get("delivery") == "delivery" else "🏪 Самовывоз"

    tg_send(ADMIN_ID,
        f"🛒 <b>Новый заказ #{data.get('id', '—')}</b>\n\n"
        f"👤 {data.get('name')} · {data.get('phone')}\n"
        f"{mode}{addr}{promo}{note}\n\n"
        f"<b>Товары:</b>\n{items}\n\n"
        f"💰 <b>Итого: {data.get('total', 0):,} ₽</b>\n"
        f"🕐 {data['serverDate']}"
    )
    return jsonify({"ok": True})

@app.route("/api/orders/<order_id>/status", methods=["PATCH"])
def update_status(order_id):
    if request.headers.get("X-Admin-Token") != ADMIN_SECRET:
        return jsonify({"error": "Нет доступа"}), 401

    orders     = load_json("orders", [])
    new_status = request.json.get("status")
    labels     = {"new":"Новый","processing":"Обрабатывается","ready":"Готов к выдаче","done":"Выдан"}

    for o in orders:
        if str(o.get("id")) == str(order_id):
            o["status"] = new_status
            save_json("orders", orders)
            if o.get("userId"):
                tg_send(o["userId"],
                    f"📦 Статус заказа <b>#{order_id}</b>:\n→ <b>{labels.get(new_status, new_status)}</b>"
                )
            return jsonify({"ok": True})
    return jsonify({"error": "Заказ не найден"}), 404

# ============================================================
# ЧАТ
# ============================================================
@app.route("/api/chat", methods=["POST"])
def receive_chat():
    data = request.json
    tg_send(ADMIN_ID,
        f"💬 <b>Сообщение от покупателя</b>\n"
        f"👤 {data.get('userName', 'Пользователь')}"
        + (f" (id: {data.get('userId')})" if data.get("userId") else "") +
        f"\n\n{data.get('text', '')}"
    )
    return jsonify({"ok": True})

# ============================================================
# TELEGRAM WEBHOOK (команды /orders /stats /help)
# ============================================================
@app.route(f"/webhook/<token>", methods=["POST"])
def telegram_webhook(token):
    if token != BOT_TOKEN:
        return "forbidden", 403

    msg     = request.json.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    user_id = msg.get("from", {}).get("id")
    text    = msg.get("text", "")
    if not chat_id or user_id != ADMIN_ID:
        return "ok"

    if text == "/start":
        tg_send(chat_id,
            "👋 Привет, администратор!\n\n"
            "Команды:\n"
            "/orders — последние заказы\n"
            "/stats  — статистика\n"
            "/help   — обновление каталога и статусов"
        )

    elif text == "/orders":
        orders = load_json("orders", [])
        if not orders:
            tg_send(chat_id, "Заказов пока нет.")
        else:
            labels = {"new":"🟡","processing":"🔵","ready":"🟢","done":"⚫"}
            lines  = [
                f"{labels.get(o.get('status','new'))} <b>#{o.get('id')}</b> · {o.get('name')} · {o.get('total',0):,} ₽"
                for o in reversed(orders[-10:])
            ]
            tg_send(chat_id, "📦 <b>Последние заказы:</b>\n\n" + "\n".join(lines))

    elif text == "/stats":
        orders = load_json("orders", [])
        tg_send(chat_id,
            f"📊 <b>Статистика TechStore</b>\n\n"
            f"📦 Заказов: {len(orders)}\n"
            f"💰 Выручка: {sum(o.get('total',0) for o in orders):,} ₽\n"
            f"🛍 Товаров: {len(load_products_from_csv())}\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )

    elif text == "/help":
        tg_send(chat_id,
            "📖 <b>Управление магазином</b>\n\n"
            "<b>Смена статуса заказа:</b>\n"
            f"<code>curl -X PATCH {SHOP_URL}/api/orders/НОМЕР/status \\\n"
            f"  -H 'X-Admin-Token: {ADMIN_SECRET}' \\\n"
            f"  -H 'Content-Type: application/json' \\\n"
            f"  -d '{{\"status\":\"processing\"}}'</code>\n\n"
            "Статусы: new | processing | ready | done"
        )
    return "ok"

def setup_webhook():
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
        json={"url": f"{SHOP_URL}/webhook/{BOT_TOKEN}"}
    )
    print(f"Webhook: {r.json()}")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Сервер запущен на порту {port}")
    if "onrender.com" in SHOP_URL:
        setup_webhook()
    app.run(host="0.0.0.0", port=port, debug=False)
