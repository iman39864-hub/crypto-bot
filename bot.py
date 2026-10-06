import time
import threading
import urllib3
import requests
import json
import os
import pandas as pd
import numpy as np
from flask import Flask, request, jsonify

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TOKEN = os.getenv('BALE_BOT_TOKEN', '1918737723:3Unqmbyfho1KwFquFN1QkY9_0v9tT-AMdmg')
BASE_URL = f'https://tapi.bale.ai/bot{TOKEN}'
DB_FILE = 'positions_db.json'

ADMIN_CHAT_ID = None

DEFAULT_MARGIN = 15.0
LEVERAGE = 10
INITIAL_BALANCE = 100.0
FEE_RATE = 0.0005

app = Flask(__name__)
ERROR_LOGS = []

def log_error_to_bale(error_msg):
    global ERROR_LOGS
    print(f"[ERROR] {error_msg}")
    ERROR_LOGS.append(error_msg)
    if len(ERROR_LOGS) > 20:
        ERROR_LOGS.pop(0)
    if ADMIN_CHAT_ID:
        send_bale_message(ADMIN_CHAT_ID, f"⚠️ **خطای سیستمی در ربات:**\n`{error_msg}`")

@app.route('/')
def home():
    return "Bot is running with Market Scanner!", 200

def load_database():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('active', []), data.get('history', []), data.get('admin_id', None), data.get('balance', INITIAL_BALANCE)
        except Exception as e:
            print(f"DB Load Error: {e}")
    return [], [], None, INITIAL_BALANCE

def save_database(active, history, admin_id, balance):
    try:
        data = {'active': active, 'history': history, 'admin_id': admin_id, 'balance': balance}
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"DB Save Error: {e}")

ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE = load_database()

def send_bale_message(chat_id, text, reply_markup=None, reply_to_message_id=None):
    if not chat_id:
        return None
    url = f"{BASE_URL}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id
    try:
        response = requests.post(url, json=payload, timeout=15, verify=False)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Send Message Error: {e}")
    return None

def edit_message_reply_markup(chat_id, message_id, reply_markup):
    if not chat_id or not message_id:
        return
    url = f"{BASE_URL}/editMessageReplyMarkup"
    payload = {'chat_id': chat_id, 'message_id': message_id, 'reply_markup': reply_markup}
    try:
        requests.post(url, json=payload, timeout=10, verify=False)
    except Exception as e:
        pass

def answer_callback_query(callback_query_id, text="انجام شد"):
    url = f"{BASE_URL}/answerCallbackQuery"
    payload = {'callback_query_id': callback_query_id, 'text': text, 'show_alert': False}
    try:
        requests.post(url, json=payload, timeout=10, verify=False)
    except Exception as e:
        pass

def get_main_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📈 پوزیشن‌های فعال", "callback_data": "active_positions"}, {"text": "📊 آمار و وین‌ریت", "callback_data": "stats"}],
            [{"text": "⚙️ وضعیت سیستم", "callback_data": "bot_status"}, {"text": "🔄 ریست کامل حساب", "callback_data": "reset_stats"}]
        ]
    }

def get_signal_keyboard(symbol, p_data=None):
    t1 = "✅ TP1 (تایید شده)" if (p_data and p_data.get('hit_tp1')) else "🎯 TP1"
    t2 = "✅ TP2 (تایید شده)" if (p_data and p_data.get('hit_tp2')) else "🎯 TP2"
    t3 = "✅ TP3 (تایید شده)" if (p_data and p_data.get('hit_tp3')) else "🎯 TP3"
    sl_text = "❌ SL (تایید شده)" if (p_data and p_data.get('hit_sl')) else "🛑 ثبت لمس SL (خروج با ضرر)"
    return {
        "inline_keyboard": [
            [{"text": t1, "callback_data": f"tp1_{symbol}"}, {"text": t2, "callback_data": f"tp2_{symbol}"}],
            [{"text": t3, "callback_data": f"tp3_{symbol}"}, {"text": sl_text, "callback_data": f"sl_{symbol}"}]
        ]
    }

def fetch_historical_candles(symbol, interval="15m", limit=100):
    url = f"https://api.toobit.com/quote/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(url, timeout=10, verify=False)
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'q_vol', 'trades', 't_buy_base', 't_buy_quote', 'ignore'])
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['open'] = df['open'].astype(float)
            df['volume'] = df['volume'].astype(float)
            return df
    except Exception as e:
        print(f"Fetch candles error for {symbol}: {e}")
    return None

def fetch_current_price(symbol):
    url = f"https://api.toobit.com/quote/v1/ticker/price?symbol={symbol}"
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(url, timeout=8, verify=False)
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            item = data[0]
            if isinstance(item, dict):
                for k in ['price', 'p', 'lastPrice', 'last']:
                    if k in item: return float(item[k])
        elif isinstance(data, dict):
            for k in ['price', 'p', 'lastPrice', 'last']:
                if k in data: return float(data[k])
            for key in ['result', 'data']:
                if key in data:
                    res = data[key]
                    if isinstance(res, dict):
                        for k in ['price', 'p', 'lastPrice', 'last']:
                            if k in res: return float(res[k])
                    elif isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict):
                        for k in ['price', 'p', 'lastPrice', 'last']:
                            if k in res[0]: return float(res[0][k])
        return None
    except Exception as e:
        return None

def calculate_indicators(df):
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['vol_ma20'] = df['volume'].rolling(window=20).mean()
    return df

def analyze_and_open_position(symbol):
    global ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE
    if any(p['symbol'] == symbol for p in ACTIVE_POSITIONS):
        return False

    df = fetch_historical_candles(symbol, "15m", 100)
    if df is None or len(df) < 30:
        return False

    df = calculate_indicators(df)
    last = df.iloc[-1]
    price = last['close']
    ema20 = last['ema20']
    ema50 = last['ema50']

    # فیلتر حجم کمی ملایم‌تر شده یا در صورت نیاز می‌توانید خط حجم را کاملاً بردارید
    signal_type = None
    if ema20 > ema50:
        signal_type = 'LONG'
    elif ema20 < ema50:
        signal_type = 'SHORT'

    if not signal_type:
        return False

    if signal_type == 'LONG':
        sl = price * 0.99
        tp1 = price * 1.008
        tp2 = price * 1.015
        tp3 = price * 1.025
    else:
        sl = price * 1.01
        tp1 = price * 0.992
        tp2 = price * 0.985
        tp3 = price * 0.975

    open_fee = (DEFAULT_MARGIN * LEVERAGE) * FEE_RATE
    PAPER_BALANCE -= open_fee

    pos = {
        'symbol': symbol, 'type': signal_type, 'entry': price, 'sl': sl,
        'tp1': tp1, 'tp2': tp2, 'tp3': tp3, 'margin': DEFAULT_MARGIN, 'status': 'ACTIVE',
        'hit_tp1': False, 'hit_tp2': False, 'hit_tp3': False, 'hit_sl': False, 'risk_free': False,
        'msg_id': None
    }
    ACTIVE_POSITIONS.append(pos)
    save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

    icon = "🚀" if signal_type == 'LONG' else "📉"
    msg = (
        f"{icon} سیگنال خودکار بازار\n"
        f"──────────────────────\n"
        f"🔹 نماد: {symbol} ({signal_type})\n"
        f"💵 قیمت ورود: {price:.4f} | مارجین: {DEFAULT_MARGIN}$\n"
        f"🎯 TP1: {tp1:.4f} | TP2: {tp2:.4f} | TP3: {tp3:.4f}\n"
        f"🛑 حد ضرر: {sl:.4f}\n"
        f"──────────────────────"
    )
    if ADMIN_CHAT_ID:
        res = send_bale_message(ADMIN_CHAT_ID, msg, reply_markup=get_signal_keyboard(symbol, pos))
        try:
            if res and 'result' in res:
                pos['msg_id'] = res['result']['message_id']
                save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
        except: pass

    return True

def calculate_pnl(entry, exit_price, position_type, margin=DEFAULT_MARGIN, leverage=LEVERAGE):
    if position_type == 'LONG':
        price_change_pct = (exit_price - entry) / entry
    else:
        price_change_pct = (entry - exit_price) / entry
    pnl_usd = margin * leverage * price_change_pct
    return pnl_usd

def close_position_completely(p, exit_price, reason="SL_HIT"):
    global ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE

    entry = p['entry']
    position_type = p['type']
    margin = p.get('margin', DEFAULT_MARGIN)

    if "TP3" in reason or "هدف نهایی" in reason:
        p['hit_tp3'] = True
        p['hit_tp1'] = True
        p['hit_tp2'] = True
    elif "SL" in reason or "ضرر" in reason:
        p['hit_sl'] = True

    if p.get('msg_id') and ADMIN_CHAT_ID:
        edit_message_reply_markup(ADMIN_CHAT_ID, p['msg_id'], get_signal_keyboard(p['symbol'], p))

    pnl_usd = calculate_pnl(entry, exit_price, position_type, margin, LEVERAGE)
    close_fee = (margin * LEVERAGE) * FEE_RATE
    net_pnl = pnl_usd - close_fee

    PAPER_BALANCE += net_pnl
    p['status'] = 'CLOSED'
    p['exit_price'] = exit_price
    p['pnl'] = net_pnl

    TRADE_HISTORY.append({'symbol': p['symbol'], 'type': position_type, 'pnl': net_pnl})
    if p in ACTIVE_POSITIONS:
        ACTIVE_POSITIONS.remove(p)

    save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

    report_text = (
        f"📢 گزارش بسته شدن معامله\n"
        f"──────────────────────\n"
        f"🔹 نماد: {p['symbol']} ({position_type})\n"
        f"💵 قیمت ورود: {entry:.4f}\n"
        f"🏁 قیمت خروج ({reason}): {exit_price:.4f}\n"
        f"💰 سود / زیان خالص: {net_pnl:+.2f} $\n"
        f"💳 **موجودی جدید حساب دمو:** {PAPER_BALANCE:.2f} $\n"
        f"──────────────────────"
    )
    if ADMIN_CHAT_ID:
        send_bale_message(ADMIN_CHAT_ID, report_text, reply_to_message_id=p.get('msg_id'))

def periodic_auto_scanner():
    symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", 
        "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "MATICUSDT",
        "LINKUSDT", "LTCUSDT", "NEARUSDT", "ATOMUSDT", "UNIUSDT",
        "APTUSDT", "FTMUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT",
        "RENDERUSDT", "FETUSDT", "INJUSDT", "PEPEUSDT", "TIAUSDT", 
        "SEIUSDT", "SHIBUSDT", "DOGSUSDT"
    ]
    while True:
        try:
            for sym in symbols:
                analyze_and_open_position(sym)
                time.sleep(0.3)
            time.sleep(60) # کاهش زمان انتظار برای بررسی سریع‌تر بازار
        except Exception as e:
            time.sleep(30)

def automated_price_monitor():
    while True:
        try:
            time.sleep(5)
            if not ACTIVE_POSITIONS: continue
            for p in list(ACTIVE_POSITIONS):
                try:
                    curr = fetch_current_price(p['symbol'])
                    if not curr: continue
                    entry = p['entry']
                    p_type = p['type']
                    margin = p.get('margin', DEFAULT_MARGIN)

                    if 'hit_tp1' not in p: p['hit_tp1'] = False
                    if 'hit_tp2' not in p: p['hit_tp2'] = False
                    if 'hit_tp3' not in p: p['hit_tp3'] = False
                    if 'hit_sl' not in p: p['hit_sl'] = False

                    hit_sl = (p_type == 'LONG' and curr <= p['sl']) or (p_type == 'SHORT' and curr >= p['sl'])
                    if hit_sl:
                        p['hit_sl'] = True
                        close_position_completely(p, p['sl'], reason="حد ضرر (SL)")
                        continue

                    hit_tp1_cond = (p_type == 'LONG' and curr >= p['tp1']) or (p_type == 'SHORT' and curr <= p['tp1'])
                    if hit_tp1_cond and not p.get('hit_tp1', False):
                        p['hit_tp1'] = True
                        p['sl'] = entry
                        p['risk_free'] = True
                        pnl_part = calculate_pnl(entry, p['tp1'], p_type, margin, LEVERAGE) * 0.4
                        fee_part = (margin * LEVERAGE * 0.4) * FEE_RATE
                        net_part = pnl_part - fee_part
                        PAPER_BALANCE += net_part
                        TRADE_HISTORY.append({'symbol': p['symbol'], 'type': p_type, 'pnl': net_part})
                        save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                        msg_tp1 = f"🎯 هدف اول (TP1) برای {p['symbol']} لمس شد!\n💰 سود خالص پله اول ({net_part:+.2f} $) واریز شد.\n🛡 حد ضرر به نقطه ورود منتقل شد."
                        if ADMIN_CHAT_ID: send_bale_message(ADMIN_CHAT_ID, msg_tp1, reply_to_message_id=p.get('msg_id'))
                        if p.get('msg_id') and ADMIN_CHAT_ID:
                            edit_message_reply_markup(ADMIN_CHAT_ID, p['msg_id'], get_signal_keyboard(p['symbol'], p))
                        continue
                except Exception as inner_ex:
                    pass
        except Exception as e:
            time.sleep(5)

def start_telegram_bot():
    global ADMIN_CHAT_ID, ACTIVE_POSITIONS, TRADE_HISTORY, PAPER_BALANCE
    offset = 0
    while True:
        try:
            url = f"{BASE_URL}/getUpdates?offset={offset}&timeout=20"
            response = requests.get(url, timeout=25, verify=False)
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    for update in data['result']:
                        offset = update['update_id'] + 1

                        if 'callback_query' in update:
                            cq = update['callback_query']
                            chat_id = cq['message']['chat']['id']
                            message_id = cq['message']['message_id']
                            data_action = cq['data']
                            answer_callback_query(cq['id'], "انجام شد ✓")

                            if data_action == 'active_positions':
                                if not ACTIVE_POSITIONS:
                                    send_bale_message(chat_id, "📈 در حال حاضر هیچ پوزیشن فعالی وجود ندارد.")
                                else:
                                    txt = "📈 پوزیشن‌های فعال دمو:\n"
                                    for p in ACTIVE_POSITIONS:
                                        txt += f"- {p['symbol']} ({p['type']}) | ورود: {p['entry']} | مارجین: {p.get('margin', DEFAULT_MARGIN)}$\n"
                                    send_bale_message(chat_id, txt)
                            elif data_action == 'stats':
                                total_trades = len(TRADE_HISTORY)
                                wins = len([t for t in TRADE_HISTORY if t.get('pnl', 0.0) > 0])
                                losses = len([t for t in TRADE_HISTORY if t.get('pnl', 0.0) <= 0])
                                win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
                                total_pnl = PAPER_BALANCE - INITIAL_BALANCE

                                stats_txt = (
                                    f"📊 گزارش حساب دمو:\n"
                                    f"──────────────────────\n"
                                    f"💳 موجودی کل حساب: {PAPER_BALANCE:.2f} $\n"
                                    f"🎯 کل بخش‌های معامله شده: {total_trades}\n"
                                    f"✅ موفق: {wins} | ❌ ناموفق: {losses}\n"
                                    f"📈 **درصد وین‌ریت:** {win_rate:.1f}%\n"
                                    f"💰 **سود/زیان خالص:** {total_pnl:+.2f} $\n"
                                    f"──────────────────────"
                                )
                                send_bale_message(chat_id, stats_txt)
                            elif data_action == 'bot_status':
                                logs_text = "\n".join(ERROR_LOGS[-5:]) if ERROR_LOGS else "هیچ خطای ثبت‌شده‌ای وجود ندارد."
                                status_msg = (
                                    f"⚙ وضعیت سیستم ربات:\n"
                                    f"• حالت کاری: اسکن خودکار بازار\n"
                                    f"• تعداد ارزهای تحت نظر: 28 ارز\n"
                                    f"• مانیتورینگ قیمت: فعال\n"
                                    f"• تنظیمات مارجین: {DEFAULT_MARGIN}$ | اهرم: {LEVERAGE}x\n\n"
                                    f"آخرین خطاها:\n{logs_text}"
                                )
                                send_bale_message(chat_id, status_msg)
                            elif data_action == 'reset_stats':
                                ACTIVE_POSITIONS = []
                                TRADE_HISTORY = []
                                PAPER_BALANCE = INITIAL_BALANCE
                                save_database([], [], ADMIN_CHAT_ID, PAPER_BALANCE)
                                send_bale_message(chat_id, f"🔄 حساب دمو ریست شد و موجودی به {INITIAL_BALANCE} دلار برگشت.")
                            elif data_action.startswith('tp1_') or data_action.startswith('tp2_') or data_action.startswith('tp3_') or data_action.startswith('sl_'):
                                parts = data_action.split('_')
                                action_type = parts[0]
                                sym = parts[1]

                                for p in ACTIVE_POSITIONS:
                                    if p['symbol'] == sym:
                                        margin = p.get('margin', DEFAULT_MARGIN)
                                        if action_type == 'tp1':
                                            p['hit_tp1'] = True
                                            p['sl'] = p['entry']
                                            p['risk_free'] = True
                                            pnl_manual = calculate_pnl(p['entry'], p['tp1'], p['type'], margin, LEVERAGE) * 0.4
                                            fee_m = (margin * LEVERAGE * 0.4) * FEE_RATE
                                            net_m = pnl_manual - fee_m
                                            PAPER_BALANCE += net_m
                                            TRADE_HISTORY.append({'symbol': sym, 'type': p['type'], 'pnl': net_m})
                                            save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                                            edit_message_reply_markup(chat_id, message_id, get_signal_keyboard(sym, p))
                                            send_bale_message(chat_id, f"✅ TP1 برای {sym} تایید و سود خالص پله اول ({net_m:+.2f} $) واریز شد.", reply_to_message_id=p.get('msg_id'))
                                        elif action_type == 'sl':
                                            p['hit_sl'] = True
                                            close_position_completely(p, p['sl'], reason="حد ضرر دستی (SL)")
                                            break

                        elif 'message' in update:
                            msg = update['message']
                            if 'text' in msg:
                                chat_id = msg['chat']['id']
                                text = msg['text'].strip()

                                if ADMIN_CHAT_ID is None:
                                    ADMIN_CHAT_ID = chat_id
                                    save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

                                if text == '/start':
                                    menu = get_main_menu_keyboard()
                                    send_bale_message(chat_id, "🤖 ربات فعال شد و بازار را اسکن می‌کند.\nلطفاً از منوی زیر استفاده کنید:", reply_markup=menu)
        except Exception as e:
            time.sleep(3)

if __name__ == '__main__':
    threading.Thread(target=automated_price_monitor, daemon=True).start()
    threading.Thread(target=periodic_auto_scanner, daemon=True).start()
    threading.Thread(target=start_telegram_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
