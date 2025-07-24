import os
import json
import asyncio
import requests
import shutil
import builtins
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# === Suppress console output ===
builtins.print = lambda *a, **k: None  # comment this out to re-enable print()

# === FILE PATHS ===
TARGETS_FILE = "targets.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AUTHORIZED_CHAT_ID = int(os.getenv("AUTHORIZED_CHAT_ID"))

bot = Bot(token=TELEGRAM_TOKEN)

# === Load Targets from JSON ===
def load_targets():
    if os.path.exists(TARGETS_FILE):
        with open(TARGETS_FILE, "r") as f:
            return json.load(f)
    return []

# === Save Targets back to JSON with backup ===
def save_targets(targets):
    shutil.copy(TARGETS_FILE, TARGETS_FILE + ".bak")
    with open(TARGETS_FILE, "w") as f:
        json.dump(targets, f, indent=2)

# === Get Token Price from CoinGecko ===
def get_token_price(token_id):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={token_id}&vs_currencies=usd"
    try:
        response = requests.get(url)
        data = response.json()
        return data.get(token_id, {}).get("usd", None)
    except Exception:
        return None

# === Main Price Monitoring Loop ===
async def check_prices():
    while True:
        targets = load_targets()
        updated_targets = []
        changes_made = False

        for token in targets:
            symbol = token["symbol"]
            token_id = token["id"]
            bounds = token.get("bounds")

            price = get_token_price(token_id)
            if price is None:
                continue

            if not bounds:
                updated_targets.append(token)
                continue

            updated_bounds = bounds.copy()

            if "lower" in bounds and price <= bounds["lower"]:
                await bot.send_message(chat_id=AUTHORIZED_CHAT_ID,
                                       text=f"🔻 {symbol} hit LOWER bound ${bounds['lower']:.5f}! Current: ${price:.5f}")
                updated_bounds.pop("lower")
                changes_made = True

            if "upper" in bounds and price >= bounds["upper"]:
                await bot.send_message(chat_id=AUTHORIZED_CHAT_ID,
                                       text=f"🚀 {symbol} hit UPPER bound ${bounds['upper']:.5f}! Current: ${price:.5f}")
                updated_bounds.pop("upper")
                changes_made = True

            if updated_bounds:
                updated_targets.append({
                    "symbol": symbol,
                    "id": token_id,
                    "bounds": updated_bounds
                })
            else:
                updated_targets.append({
                    "symbol": symbol,
                    "id": token_id
                })

        if changes_made:
            save_targets(updated_targets)

        await asyncio.sleep(60)

# === Telegram Bot Command Handling ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != AUTHORIZED_CHAT_ID:
        return

    msg = update.message.text.strip().lower()

    if msg == "list":
        targets = load_targets()
        if not targets:
            await update.message.reply_text("📭 No tokens are being tracked right now.")
        else:
            symbol_list = "\n".join([f"• {t['symbol']}" for t in targets])
            await update.message.reply_text(f"📄 Currently tracking:\n{symbol_list}")
        return

    elif msg.startswith("price "):
        symbol = msg.replace("price ", "").strip().upper()
        targets = load_targets()
        for token in targets:
            if token["symbol"].upper() == symbol:
                price = get_token_price(token["id"])
                if price is not None:
                    await update.message.reply_text(f"💰 {symbol} price: ${price:.5f}")
                else:
                    await update.message.reply_text("⚠️ Could not fetch price.")
                return
        await update.message.reply_text(f"❓ Symbol '{symbol}' not found in targets.json")
        return

    elif msg.startswith("add "):
        parts = msg.split()
        if len(parts) < 3:
            await update.message.reply_text("⚠️ Format: add SYMBOL ID [lower=XX] [upper=YY]")
            return

        symbol = parts[1].upper()
        token_id = parts[2]
        bounds = {}
        for p in parts[3:]:
            if "=" in p:
                k, v = p.split("=")
                try:
                    bounds[k] = float(v)
                except ValueError:
                    await update.message.reply_text(f"⚠️ Invalid value for {k}: {v}")
                    return

        targets = load_targets()
        if any(t["symbol"].upper() == symbol for t in targets):
            await update.message.reply_text(f"❗ Token {symbol} already exists.")
            return

        new_entry = {
            "symbol": symbol,
            "id": token_id
        }
        if bounds:
            new_entry["bounds"] = bounds

        targets.append(new_entry)
        save_targets(targets)

        bdesc = ""
        if bounds:
            bdesc = " with bounds " + ", ".join(f"{k}={v}" for k, v in bounds.items())
        await update.message.reply_text(f"✅ Added {symbol} ({token_id}){bdesc}")
        return

    elif msg.startswith("show "):
        symbol = msg.replace("show ", "").strip().upper()
        targets = load_targets()
        for token in targets:
            if token["symbol"].upper() == symbol:
                lines = [f"🔎 {symbol} details:",
                         f"• ID: {token['id']}"]
                bounds = token.get("bounds")
                if bounds:
                    if "lower" in bounds:
                        lines.append(f"• Lower Bound: ${bounds['lower']}")
                    if "upper" in bounds:
                        lines.append(f"• Upper Bound: ${bounds['upper']}")
                else:
                    lines.append("• No bounds set")
                await update.message.reply_text("\n".join(lines))
                return
        await update.message.reply_text(f"❓ Symbol '{symbol}' not found.")
        return

    elif msg.startswith("remove "):
        symbol = msg.replace("remove ", "").strip().upper()
        targets = load_targets()
        new_targets = [t for t in targets if t["symbol"].upper() != symbol]
        if len(new_targets) == len(targets):
            await update.message.reply_text(f"❌ Symbol '{symbol}' was not found.")
        else:
            save_targets(new_targets)
            await update.message.reply_text(f"🗑️ Removed {symbol} from tracking.")
        return

    elif msg == "help":
        help_text = (
            "🤖 Available Commands:\n"
            "• price SYMBOL — Get the current price (e.g. price SOL)\n"
            "• list — Show all tracked tokens\n"
            "• show SYMBOL — View full details of a token\n"
            "• add SYMBOL ID [lower=XX] [upper=YY] — Add a new token to monitor\n"
            "• remove SYMBOL — Stop monitoring a token\n"
            "• help — Show this help message\n\n"
            "ℹ️ How to find a token’s ID:\n"
            "1. Go to https://www.coingecko.com\n"
            "2. Search for the token name\n"
            "3. Click the result\n"
            "4. Copy the part after /coins/ in the URL (that’s the ID)\n\n"
            "Example:\n"
            "add SOL solana lower=180 upper=220"
        )
        await update.message.reply_text(help_text)
        return

    else:
        await update.message.reply_text("❓ Unknown command. Type help to see available commands.")

# === Start Bot ===
def start():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(check_prices())
    app.run_polling()

if __name__ == "__main__":
    start()
