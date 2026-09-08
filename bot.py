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
CHANNEL_ID = '@Trade_iman'

app = Flask(__name__)

# لیست برای ذخیره موقت لاگ‌های خطا جهت مشاهده در صورت نیاز
ERROR_LOGS = []

def log_error_to_bale(error_msg):
    global ERROR_LOGS
    ERROR_LOGS.append(error_msg)
    if len(ERROR_LOGS) > 20:
        ERROR_LOGS.pop(0)
    if ADMIN_CHAT_ID:
        send_bale_message(ADMIN_CHAT_ID, f"⚠️ **خطای سیستمی در ربات:**\n`{error_msg}`")

@app.route('/')
def home():
    return "Bot is running successfully!", 200

def load_database():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('active', []), data.get('history', []), data.get('admin_id', None), data.get('balance', 1000.0)
        except Exception as e:
            log_error_to_bale(f"خطا در خواندن دیتابیس: {e}")
    return [], [], None, 1000.0

def save_database(active, history, admin_id, balance):
    try:
        data = {'active': active, 'history': history, 'admin_id': admin_id, 'balance': balance}
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        log_error_to_bale(f"خطا در ذخیره دیتابیس: {e}")

ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE = load_database()

def send_bale_message(chat_id, text, reply_markup=None):
    if not chat_id:
        return None
    url = f"{BASE_URL}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    try:
        response = requests.post(url, json=payload, timeout=15, verify=False)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        pass 
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
            [
                {"text": "📊 اسکن هوشمند بازار", "callback_data": "scan_market"}
            ],
            [
                {"text": "📈 پوزیشن‌های فعال", "callback_data": "active_positions"},
                {"text": "📊 آمار و وین‌ریت", "callback_data": "stats"}
            ],
            [
                {"text": "⚙️ وضعیت و لاگ خطا", "callback_data": "bot_status"},
                {"text": "🔄 ریست کامل حساب", "callback_data": "reset_stats"}
            ]
        ]
    }

def get_signal_keyboard(symbol, p_data=None):
    t1 = "✅ TP1 (تایید شده)" if (p_data and p_data.get('hit_tp1')) else "🎯 ثبت لمس TP1"
    t2 = "✅ TP2 (تایید شده)" if (p_data and p_data.get('hit_tp2')) else "🎯 ثبت لمس TP2"
    t3 = "✅ TP3 (تایید شده)" if (p_data and p_data.get('hit_tp3')) else "🎯 ثبت لمس TP3"

    return {
        "inline_keyboard": [
            [
                {"text": t1, "callback_data": f"tp1_{symbol}"},
                {"text": t2, "callback_data": f"tp2_{symbol}"}
            ],
            [
                {"text": t3, "callback_data": f"tp3_{symbol}"},
                {"text": "🛑 بستن دستی (SL)", "callback_data": f"close_{symbol}"}
            ]
        ]
    }

def fetch_toobit_candles(symbol, interval='15m', limit=300):
    url = f"https://api.toobit.com/quote/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    session = requests.Session()
    session.trust_env = False
    for attempt in range(2):
        try:
            response = session.get(url, timeout=15, verify=False)
            data = response.json()
            if not isinstance(data, list) or len(data) == 0: return None
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'not', 'tbav', 'tbqav'])
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            return df
        except Exception as e:
            time.sleep(1)
    return None

def fetch_current_price(symbol):
    url = f"https://api.toobit.com/quote/v1/ticker/price?symbol={symbol}"
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(url, timeout=8, verify=False)
        data = response.json()
        if isinstance(data, list) and len(data) > 0 and 'price' in data[0]: return float(data[0]['price'])
        elif isinstance(data, dict):
            if 'price' in data: return float(data['price'])
            elif 'result' in data and 'price' in data['result']: return float(data['result']['price'])
            elif 'data' in data and isinstance(data['data'], dict) and 'price' in data['data']: return float(data['data']['price'])
        return None
    except Exception as e:
        return None

def calculate_indicators_with_adx(df, period=14):
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()

    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))

    df['high_diff'] = df['high'].diff()
    df['low_diff'] = -df['low'].diff()
    df['plus_dm'] = np.where((df['high_diff'] > df['low_diff']) & (df['high_diff'] > 0), df['high_diff'], 0.0)
    df['minus_dm'] = np.where((df['low_diff'] > df['high_diff']) & (df['low_diff'] > 0), df['low_diff'], 0.0)

    df['tr'] = pd.concat([(df['high'] - df['low']), (df['high'] - df['close'].shift()).abs(), (df['low'] - df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()

    df['smooth_plus_dm'] = pd.Series(df['plus_dm']).rolling(window=period).mean()
    df['smooth_minus_dm'] = pd.Series(df['minus_dm']).rolling(window=period).mean()
    df['smooth_tr'] = df['tr'].rolling(window=period).mean()

    df['plus_di'] = (df['smooth_plus_dm'] / (df['smooth_tr'] + 1e-10)) * 100
    df['minus_di'] = (df['smooth_minus_dm'] / (df['smooth_tr'] + 1e-10)) * 100

    dx_den = (df['plus_di'] + df['minus_di'])
    df['dx'] = (abs(df['plus_di'] - df['minus_di']) / (dx_den + 1e-10)) * 100
    df['adx'] = df['dx'].rolling(window=period).mean()
    return df

def analyze_market_structure(df):
    recent_highs = df['high'].iloc[-25:-2]
    recent_lows = df['low'].iloc[-25:-2]
    major_resistance = recent_highs.max()
    major_support = recent_lows.min()
    current_close = df['close'].iloc[-2]
    prev_close = df['close'].iloc[-3]
    bullish_bos = (prev_close <= major_resistance) and (current_close > major_resistance)
    bearish_bos = (prev_close >= major_support) and (current_close < major_support)
    return bullish_bos, bearish_bos, major_support, major_resistance

def close_position_automatically(p, exit_price, reason="SL_HIT"):
    global ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE

    entry = p['entry']
    position_type = p['type']
    trade_size = 100.0

    if position_type == 'LONG':
        pnl_percent = (exit_price - entry) / entry
    else:
        pnl_percent = (entry - exit_price) / entry

    pnl_usd = trade_size * pnl_percent
    PAPER_BALANCE += pnl_usd

    p['status'] = 'CLOSED'
    p['exit_price'] = exit_price
    p['pnl'] = pnl_usd

    TRADE_HISTORY.append({'symbol': p['symbol'], 'type': position_type, 'pnl': pnl_usd})
    save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

    report_text = (
        f"📢 گزارش خودکار بسته شدن معامله (دمو) \n"
        f"──────────────────────\n"
        f"🔹 نماد: {p['symbol']} ({position_type})\n"
        f"💵 قیمت ورود: {entry:.4f}\n"
        f"🏁 قیمت خروج ({reason}): {exit_price:.4f}\n"
        f"💰 سود / زیان معامله: {pnl_usd:+.2f} $\n"
        f"💳 **موجودی جدید حساب دمو:** {PAPER_BALANCE:.2f} $\n"
        f"──────────────────────"
    )
    if ADMIN_CHAT_ID:
        send_bale_message(ADMIN_CHAT_ID, report_text)
    if CHANNEL_ID:
        send_bale_message(CHANNEL_ID, report_text)

def scan_and_notify(chat_id, notify_if_empty=False):
    global ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, CHANNEL_ID, PAPER_BALANCE
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'DOGEUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOTUSDT']
    signals_found = 0
    for symbol in symbols:
        try:
            if any(p['symbol'] == symbol and p['status'] == 'ACTIVE' for p in ACTIVE_POSITIONS): continue
            df_15m = fetch_toobit_candles(symbol, '15m', 300)
            df_1h = fetch_toobit_candles(symbol, '1h', 300)
            if df_15m is None or df_1h is None: continue

            df_15m = calculate_indicators_with_adx(df_15m)
            df_1h = calculate_indicators_with_adx(df_1h)

            atr = float(df_15m['atr'].iloc[-2])
            rsi = float(df_15m['rsi'].iloc[-2])
            adx = float(df_15m['adx'].iloc[-2])
            ema_200_val = float(df_15m['ema200'].iloc[-2])

            if pd.isna(atr) or atr <= 0 or pd.isna(adx): continue
            if adx < 20: continue

            current_close = float(df_15m['close'].iloc[-2])
            trend_1h_up = (df_1h['close'].iloc[-2] > df_1h['ema50'].iloc[-2]) and (current_close > ema_200_val)
            trend_1h_down = (df_1h['close'].iloc[-2] < df_1h['ema50'].iloc[-2]) and (current_close < ema_200_val)

            bullish_bos, bearish_bos, major_support, major_resistance = analyze_market_structure(df_15m)

            is_long = bool(trend_1h_up and bullish_bos and (30 < rsi < 80))
            is_short = bool(trend_1h_down and bearish_bos and (20 < rsi < 70))

            if is_long or is_short:
                realtime_price = fetch_current_price(symbol) or current_close

                if is_long:
                    sl = min(major_support - (0.3 * atr), realtime_price - (1.0 * atr))
                    tp1 = realtime_price + (1.5 * atr)
                    tp2 = realtime_price + (3.0 * atr)
                    tp3 = realtime_price + (4.5 * atr)
                    signals_found += 1

                    pos = {
                        'symbol': symbol, 'type': 'LONG', 'entry': realtime_price, 'sl': sl,
                        'tp1': tp1, 'tp2': tp2, 'tp3': tp3, 'status': 'ACTIVE',
                        'hit_tp1': False, 'hit_tp2': False, 'hit_tp3': False, 'risk_free': False,
                        'msg_id': None
                    }
                    ACTIVE_POSITIONS.append(pos)
                    save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

                    msg = (
                        f"🚀 سیگنال دمو جدید (LONG) \n"
                        f"──────────────────────\n"
                        f"🔹 نماد: {symbol}\n"
                        f"💵 قیمت ورود: {realtime_price:.4f}\n"
                        f"🎯 TP1: {tp1:.4f}\n"
                        f"🎯 TP2: {tp2:.4f}\n"
                        f"🎯 TP3: {tp3:.4f}\n"
                        f"🛑 حد ضرر اولیه: {sl:.4f}\n"
                        f"──────────────────────"
                    )
                    if ADMIN_CHAT_ID:
                        res = send_bale_message(ADMIN_CHAT_ID, msg, reply_markup=get_signal_keyboard(symbol, pos))
                        try:
                            if res and 'result' in res:
                                pos['msg_id'] = res['result']['message_id']
                                save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                        except: pass
                    if CHANNEL_ID:
                        send_bale_message(CHANNEL_ID, msg)

                elif is_short:
                    sl = max(major_resistance + (0.3 * atr), realtime_price + (1.0 * atr))
                    tp1 = realtime_price - (1.5 * atr)
                    tp2 = realtime_price - (3.0 * atr)
                    tp3 = realtime_price - (4.5 * atr)
                    signals_found += 1

                    pos = {
                        'symbol': symbol, 'type': 'SHORT', 'entry': realtime_price, 'sl': sl,
                        'tp1': tp1, 'tp2': tp2, 'tp3': tp3, 'status': 'ACTIVE',
                        'hit_tp1': False, 'hit_tp2': False, 'hit_tp3': False, 'risk_free': False,
                        'msg_id': None
                    }
                    ACTIVE_POSITIONS.append(pos)
                    save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

                    msg = (
                        f"📉 سیگنال دمو جدید (SHORT) \n"
                        f"──────────────────────\n"
                        f"🔹 نماد: {symbol}\n"
                        f"💵 قیمت ورود: {realtime_price:.4f}\n"
                        f"🎯 TP1: {tp1:.4f}\n"
                        f"🎯 TP2: {tp2:.4f}\n"
                        f"🎯 TP3: {tp3:.4f}\n"
                        f"🛑 حد ضرر اولیه: {sl:.4f}\n"
                        f"──────────────────────"
                    )
                    if ADMIN_CHAT_ID:
                        res = send_bale_message(ADMIN_CHAT_ID, msg, reply_markup=get_signal_keyboard(symbol, pos))
                        try:
                            if res and 'result' in res:
                                pos['msg_id'] = res['result']['message_id']
                                save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                        except: pass
                    if CHANNEL_ID:
                        send_bale_message(CHANNEL_ID, msg)
        except Exception as ex:
            log_error_to_bale(f"Scan error on {symbol}: {ex}")

    if notify_if_empty and signals_found == 0 and chat_id:
        send_bale_message(chat_id, "🔍 اسکن انجام شد. در حال حاضر شرایط بازار با این فیلترها مطابقت نداشت.")

@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    global ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "No JSON data received"}), 400

        symbol = data.get('symbol', 'BTCUSDT').upper()
        position_type = data.get('type', 'LONG').upper()

        price = fetch_current_price(symbol) or float(data.get('price', 60000.0))
        sl = float(data.get('sl', price * 0.99 if position_type == 'LONG' else price * 1.01))
        tp1 = float(data.get('tp1', price * 1.01 if position_type == 'LONG' else price * 0.99))
        tp2 = float(data.get('tp2', price * 1.02 if position_type == 'LONG' else price * 0.98))
        tp3 = float(data.get('tp3', price * 1.03 if position_type == 'LONG' else price * 0.97))

        if any(p['symbol'] == symbol and p['status'] == 'ACTIVE' for p in ACTIVE_POSITIONS):
            return jsonify({"status": "error", "message": "Active position already exists for this symbol"}), 400

        pos = {
            'symbol': symbol, 'type': position_type, 'entry': price, 'sl': sl,
            'tp1': tp1, 'tp2': tp2, 'tp3': tp3, 'status': 'ACTIVE',
            'hit_tp1': False, 'hit_tp2': False, 'hit_tp3': False, 'risk_free': False,
            'msg_id': None
        }
        ACTIVE_POSITIONS.append(pos)
        save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

        icon = "🚀" if position_type == 'LONG' else "📉"
        msg = (
            f"{icon} سیگنال تریدینگ‌ویو ({position_type}) \n"
            f"──────────────────────\n"
            f"🔹 نماد: {symbol}\n"
            f"💵 قیمت ورود: {price:.4f}\n"
            f"🎯 TP1: {tp1:.4f}\n"
            f"🎯 TP2: {tp2:.4f}\n"
            f"🎯 TP3: {tp3:.4f}\n"
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
        if CHANNEL_ID:
            send_bale_message(CHANNEL_ID, msg)

        return jsonify({"status": "success", "message": "Signal processed successfully"}), 200
    except Exception as e:
        log_error_to_bale(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def automated_price_monitor():
    global ADMIN_CHAT_ID, ACTIVE_POSITIONS, TRADE_HISTORY, PAPER_BALANCE
    while True:
        try:
            time.sleep(5)
            actives = [x for x in ACTIVE_POSITIONS if x['status'] == 'ACTIVE']
            if not actives:
                time.sleep(5)
                continue

            for p in actives:
                curr = fetch_current_price(p['symbol'])
                if not curr:
                    continue

                hit_sl = (p['type'] == 'LONG' and curr <= p['sl']) or (p['type'] == 'SHORT' and curr >= p['sl'])
                if hit_sl:
                    close_position_automatically(p, curr, reason="حد ضرر (SL)")
                    continue

                hit_tp3 = (p['type'] == 'LONG' and curr >= p['tp3']) or (p['type'] == 'SHORT' and curr <= p['tp3'])
                if hit_tp3:
                    close_position_automatically(p, curr, reason="هدف نهایی (TP3)")
                    continue

                if not p.get('hit_tp1', False):
                    hit_tp1_cond = (p['type'] == 'LONG' and curr >= p['tp1']) or (p['type'] == 'SHORT' and curr <= p['tp1'])
                    if hit_tp1_cond:
                        p['hit_tp1'] = True
                        p['sl'] = p['entry']
                        p['risk_free'] = True
                        save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                        
                        msg_tp1 = f"🎯 هدف اول (TP1) برای {p['symbol']} لمس شد!\n🛡️ حد ضرر به نقطه ورود منتقل گردید (ریسک‌فری شد) اما معامله همچنان باز است."
                        if ADMIN_CHAT_ID:
                            send_bale_message(ADMIN_CHAT_ID, msg_tp1)
                        if CHANNEL_ID:
                            send_bale_message(CHANNEL_ID, msg_tp1)
                            
                        if p.get('msg_id') and ADMIN_CHAT_ID:
                            edit_message_reply_markup(ADMIN_CHAT_ID, p['msg_id'], get_signal_keyboard(p['symbol'], p))

                if not p.get('hit_tp2', False):
                    hit_tp2_cond = (p['type'] == 'LONG' and curr >= p['tp2']) or (p['type'] == 'SHORT' and curr <= p['tp2'])
                    if hit_tp2_cond:
                        p['hit_tp2'] = True
                        save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                        
                        msg_tp2 = f"🎯 هدف دوم (TP2) برای {p['symbol']} لمس شد!\n📈 معامله همچنان برای رسیدن به TP3 باز است."
                        if ADMIN_CHAT_ID:
                            send_bale_message(ADMIN_CHAT_ID, msg_tp2)
                        if CHANNEL_ID:
                            send_bale_message(CHANNEL_ID, msg_tp2)
                            
                        if p.get('msg_id') and ADMIN_CHAT_ID:
                            edit_message_reply_markup(ADMIN_CHAT_ID, p['msg_id'], get_signal_keyboard(p['symbol'], p))

        except Exception as e:
            log_error_to_bale(f"Monitor loop error: {e}")
            time.sleep(5)

def automated_background_scanner():
    global ADMIN_CHAT_ID
    while True:
        try:
            time.sleep(1200)
            if ADMIN_CHAT_ID:
                scan_and_notify(ADMIN_CHAT_ID, notify_if_empty=False)
        except Exception as e:
            log_error_to_bale(f"Background scanner error: {e}")
            time.sleep(60)

def run_flask_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def start_bot():
    global ADMIN_CHAT_ID, ACTIVE_POSITIONS, TRADE_HISTORY, PAPER_BALANCE
    offset = 0

    threading.Thread(target=run_flask_server, daemon=True).start()
    threading.Thread(target=automated_background_scanner, daemon=True).start()
    threading.Thread(target=automated_price_monitor, daemon=True).start()

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

                            if data_action == 'scan_market':
                                send_bale_message(chat_id, "🔍 اسکن بازار شروع شد...")
                                threading.Thread(target=scan_and_notify, args=(chat_id, True)).start()
                            elif data_action == 'active_positions':
                                actives = [p for p in ACTIVE_POSITIONS if p['status'] == 'ACTIVE']
                                if not actives:
                                    send_bale_message(chat_id, "📈 در حال حاضر هیچ پوزیشن فعالی وجود ندارد.")
                                else:
                                    txt = "📈 پوزیشن‌های فعال دمو:\n"
                                    for p in actives:
                                        txt += f"- {p['symbol']} ({p['type']}) | ورود: {p['entry']} | حد ضرر: {p['sl']}\n"
                                    send_bale_message(chat_id, txt)
                            elif data_action == 'stats':
                                total_trades = len(TRADE_HISTORY)
                                wins = len([t for t in TRADE_HISTORY if t.get('pnl', 0.0) > 0])
                                losses = len([t for t in TRADE_HISTORY if t.get('pnl', 0.0) <= 0])
                                win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
                                total_pnl = sum([t.get('pnl', 0.0) for t in TRADE_HISTORY])

                                stats_txt = (
                                    f"📊 گزارش حساب دمو و وین‌ریت:\n"
                                    f"──────────────────────\n"
                                    f"💳 موجودی کل حساب: {PAPER_BALANCE:.2f} $\n"
                                    f"🎯 کل معاملات بسته شده: {total_trades}\n"
                                    f"✅ موفق: {wins} | ❌ ناموفق: {losses}\n"
                                    f"📈 **درصد وین‌ریت:** {win_rate:.1f}%\n"
                                    f"💰 **سود/زیان خالص:** {total_pnl:+.2f} $\n"
                                    f"──────────────────────"
                                )
                                send_bale_message(chat_id, stats_txt)
                            elif data_action == 'bot_status':
                                logs_text = "\n".join(ERROR_LOGS[-5:]) if ERROR_LOGS else "هیچ خطای ثبت‌شده‌ای وجود ندارد."
                                status_msg = (
                                    f"⚙️ وضعیت سیستم ربات:\n"
                                    f"• مانیتورینگ قیمت: فعال\n"
                                    f"• تعداد خطاهای اخیر ثبت شده: {len(ERROR_LOGS)}\n\n"
                                    f"آخرین خطاها:\n{logs_text}"
                                )
                                send_bale_message(chat_id, status_msg)
                            elif data_action == 'reset_stats':
                                ACTIVE_POSITIONS = []
                                TRADE_HISTORY = []
                                PAPER_BALANCE = 1000.0
                                save_database([], [], ADMIN_CHAT_ID, PAPER_BALANCE)
                                send_bale_message(chat_id, "🔄 حساب دمو ریست شد و موجودی به ۱۰۰۰ دلار برگشت.")

                            elif data_action.startswith('tp1_') or data_action.startswith('tp2_') or data_action.startswith('tp3_') or data_action.startswith('close_'):
                                parts = data_action.split('_')
                                action_type = parts[0]
                                sym = parts[1]

                                for p in ACTIVE_POSITIONS:
                                    if p['symbol'] == sym and p['status'] == 'ACTIVE':
                                        if action_type == 'tp1':
                                            p['hit_tp1'] = True
                                            p['sl'] = p['entry']
                                            p['risk_free'] = True
                                            save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                                            edit_message_reply_markup(chat_id, message_id, get_signal_keyboard(sym, p))
                                            send_bale_message(chat_id, f"✅ TP1 برای {sym} تایید و ریسک‌فری شد (معامله باز است).")
                                        elif action_type == 'tp2':
                                            p['hit_tp2'] = True
                                            save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                                            edit_message_reply_markup(chat_id, message_id, get_signal_keyboard(sym, p))
                                            send_bale_message(chat_id, f"✅ TP2 برای {sym} ثبت شد (معامله باز است).")
                                        elif action_type == 'tp3' or action_type == 'close':
                                            curr_p = fetch_current_price(sym) or p['entry']
                                            close_position_automatically(p, curr_p, reason="بستن دستی / اتمام معامله")
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
                                    send_bale_message(chat_id, "🤖 پنل حساب دموی خودکار ربات\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=menu)
        except Exception as e:
            time.sleep(3)

if __name__ == '__main__':
    start_bot()
