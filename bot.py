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
CHANNEL_ID = None

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
    return "Bot is running successfully!", 200

def load_database():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('active', []), data.get('history', []), data.get('admin_id', None), data.get('balance', 1000.0)
        except Exception as e:
            print(f"DB Load Error: {e}")
    return [], [], None, 1000.0

def save_database(active, history, admin_id, balance):
    try:
        data = {'active': active, 'history': history, 'admin_id': admin_id, 'balance': balance}
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"DB Save Error: {e}")

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
            [{"text": "📊 اسکن هوشمند بازار", "callback_data": "scan_market"}],
            [{"text": "📈 پوزیشن‌های فعال", "callback_data": "active_positions"}, {"text": "📊 آمار و وین‌ریت", "callback_data": "stats"}],
            [{"text": "⚙️ وضعیت و لاگ خطا", "callback_data": "bot_status"}, {"text": "🔄 ریست کامل حساب", "callback_data": "reset_stats"}]
        ]
    }

def get_signal_keyboard(symbol, p_data=None):
    t1 = "✅ TP1 (تایید شده)" if (p_data and p_data.get('hit_tp1')) else "🎯 TP1"
    t2 = "✅ TP2 (تایید شده)" if (p_data and p_data.get('hit_tp2')) else "🎯 TP2"
    t3 = "✅ TP3 (تایید شده)" if (p_data and p_data.get('hit_tp3')) else "🎯 TP3"
    return {
        "inline_keyboard": [
            [{"text": t1, "callback_data": f"tp1_{symbol}"}, {"text": t2, "callback_data": f"tp2_{symbol}"}],
            [{"text": t3, "callback_data": f"tp3_{symbol}"}, {"text": "🛑 ثبت لمس SL (خروج با ضرر)", "callback_data": f"sl_{symbol}"}]
        ]
    }

def fetch_toobit_candles(symbol, interval='15m', limit=200):
    url = f"https://api.toobit.com/quote/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    session = requests.Session()
    session.trust_env = False
    for _ in range(2):
        try:
            response = session.get(url, timeout=15, verify=False)
            data = response.json()
            if not isinstance(data, list) or len(data) == 0: return None
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'not', 'tbav', 'tbqav'])
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            return df
        except Exception:
            time.sleep(1)
    return None

def fetch_current_price(symbol):
    url = f"https://api.toobit.com/quote/v1/ticker/price?symbol={symbol}"
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(url, timeout=8, verify=False)
        data = response.json()
        
        # پشتیبانی کامل از تمامی ساختارهای احتمالی پاسخ صرافی بدون ایجاد خطای آزاردهنده
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

def calculate_indicators(df, period=14):
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))
    tr = pd.concat([(df['high'] - df['low']), (df['high'] - df['close'].shift()).abs(), (df['low'] - df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=period).mean()
    return df

def close_position_completely(p, exit_price, reason="SL_HIT"):
    global ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE

    entry = p['entry']
    position_type = p['type']
    
    if position_type == 'LONG':
        pnl_usd = ((exit_price - entry) / entry) * 1000.0
    else:
        pnl_usd = ((entry - exit_price) / entry) * 1000.0

    if abs(pnl_usd) < 0.01:
        pnl_usd = 5.0 if (reason != "حد ضرر (SL)" and reason != "حد ضرر دستی (SL)") else -5.0

    PAPER_BALANCE += pnl_usd

    p['status'] = 'CLOSED'
    p['exit_price'] = exit_price
    p['pnl'] = pnl_usd

    TRADE_HISTORY.append({'symbol': p['symbol'], 'type': position_type, 'pnl': pnl_usd})
    
    if p in ACTIVE_POSITIONS:
        ACTIVE_POSITIONS.remove(p)

    save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

    report_text = (
        f"📢 گزارش بسته شدن معامله (دمو) \n"
        f"──────────────────────\n"
        f"🔹 نماد: {p['symbol']} ({position_type})\n"
        f"💵 قیمت ورود: {entry:.4f}\n"
        f"🏁 قیمت خروج ({reason}): {exit_price:.4f}\n"
        f"💰 سود / زیان معامله: {pnl_usd:+.2f} $\n"
        f"💳 **موجودی جدید حساب دمو:** {PAPER_BALANCE:.2f} $\n"
        f"──────────────────────"
    )
    print(f"Closed trade: {p['symbol']} with PnL: {pnl_usd}")
    if ADMIN_CHAT_ID:
        send_bale_message(ADMIN_CHAT_ID, report_text)

def scan_and_notify(chat_id, notify_if_empty=False):
    global ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'DOGEUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOTUSDT']
    signals_found = 0
    for symbol in symbols:
        try:
            if any(p['symbol'] == symbol for p in ACTIVE_POSITIONS): continue
            df_15m = fetch_toobit_candles(symbol, '15m', 200)
            if df_15m is None: continue

            df_15m = calculate_indicators(df_15m)
            atr = float(df_15m['atr'].iloc[-2])
            rsi = float(df_15m['rsi'].iloc[-2])
            ema50 = float(df_15m['ema50'].iloc[-2])
            current_close = float(df_15m['close'].iloc[-2])

            if pd.isna(atr) or atr <= 0 or pd.isna(rsi): continue

            is_long = (current_close > ema50) and (rsi < 65) and (rsi > 40)
            is_short = (current_close < ema50) and (rsi > 35) and (rsi < 60)

            if is_long or is_short:
                realtime_price = fetch_current_price(symbol) or current_close

                if is_long:
                    sl = realtime_price - (1.5 * atr)
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
                        f"🚀 سیگنال خودکار بازار (LONG) \n"
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

                elif is_short:
                    sl = realtime_price + (1.5 * atr)
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
                        f"📉 سیگنال خودکار بازار (SHORT) \n"
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
        except Exception as ex:
            print(f"Scan error on {symbol}: {ex}")

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

        if any(p['symbol'] == symbol for p in ACTIVE_POSITIONS):
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

        return jsonify({"status": "success", "message": "Signal processed successfully"}), 200
    except Exception as e:
        log_error_to_bale(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def automated_price_monitor():
    global ADMIN_CHAT_ID, ACTIVE_POSITIONS, TRADE_HISTORY, PAPER_BALANCE
    print("Price monitor background thread started successfully.")
    while True:
        try:
            time.sleep(5)
            if not ACTIVE_POSITIONS:
                continue

            for p in list(ACTIVE_POSITIONS):
                try:
                    curr = fetch_current_price(p['symbol'])
                    if not curr:
                        continue

                    entry = p['entry']
                    p_type = p['type']

                    if 'hit_tp1' not in p: p['hit_tp1'] = False
                    if 'hit_tp2' not in p: p['hit_tp2'] = False
                    if 'hit_tp3' not in p: p['hit_tp3'] = False

                    # 1. بررسی حد ضرر (SL)
                    hit_sl = (p_type == 'LONG' and curr <= p['sl']) or (p_type == 'SHORT' and curr >= p['sl'])
                    if hit_sl:
                        close_position_completely(p, p['sl'], reason="حد ضرر (SL)")
                        continue

                    # 2. بررسی TP3
                    hit_tp3_cond = (p_type == 'LONG' and curr >= p['tp3']) or (p_type == 'SHORT' and curr <= p['tp3'])
                    if hit_tp3_cond and not p.get('hit_tp3', False):
                        p['hit_tp3'] = True
                        close_position_completely(p, p['tp3'], reason="هدف نهایی (TP3)")
                        continue

                    # 3. بررسی TP2
                    hit_tp2_cond = (p_type == 'LONG' and curr >= p['tp2']) or (p_type == 'SHORT' and curr <= p['tp2'])
                    if hit_tp2_cond and not p.get('hit_tp2', False):
                        if not p.get('hit_tp1', False):
                            p['hit_tp1'] = True
                            p['sl'] = entry  
                            p['risk_free'] = True
                            pnl_part1 = 15.0
                            PAPER_BALANCE += pnl_part1
                            TRADE_HISTORY.append({'symbol': p['symbol'], 'type': p_type, 'pnl': pnl_part1})
                            msg_tp1 = f"🎯 هدف اول (TP1) برای {p['symbol']} لمس شد!\n💰 سود پله اول ({pnl_part1:+.2f} $) واریز شد.\n🛡️ حد ضرر به نقطه ورود منتقل شد."
                            if ADMIN_CHAT_ID: send_bale_message(ADMIN_CHAT_ID, msg_tp1)

                        p['hit_tp2'] = True
                        pnl_part2 = 25.0
                        PAPER_BALANCE += pnl_part2
                        TRADE_HISTORY.append({'symbol': p['symbol'], 'type': p_type, 'pnl': pnl_part2})
                        save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

                        msg_tp2 = f"🎯 هدف دوم (TP2) برای {p['symbol']} لمس شد!\n💰 سود پله دوم ({pnl_part2:+.2f} $) واریز شد."
                        if ADMIN_CHAT_ID: send_bale_message(ADMIN_CHAT_ID, msg_tp2)
                        if p.get('msg_id') and ADMIN_CHAT_ID:
                            edit_message_reply_markup(ADMIN_CHAT_ID, p['msg_id'], get_signal_keyboard(p['symbol'], p))
                        continue

                    # 4. بررسی TP1
                    hit_tp1_cond = (p_type == 'LONG' and curr >= p['tp1']) or (p_type == 'SHORT' and curr <= p['tp1'])
                    if hit_tp1_cond and not p.get('hit_tp1', False):
                        p['hit_tp1'] = True
                        p['sl'] = entry  
                        p['risk_free'] = True
                        
                        pnl_part = 15.0
                        PAPER_BALANCE += pnl_part
                        TRADE_HISTORY.append({'symbol': p['symbol'], 'type': p_type, 'pnl': pnl_part})
                        save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

                        msg_tp1 = f"🎯 هدف اول (TP1) برای {p['symbol']} لمس شد!\n💰 سود پله اول ({pnl_part:+.2f} $) واریز شد.\n🛡️ حد ضرر به نقطه ورود منتقل شد."
                        if ADMIN_CHAT_ID: send_bale_message(ADMIN_CHAT_ID, msg_tp1)
                        if p.get('msg_id') and ADMIN_CHAT_ID:
                            edit_message_reply_markup(ADMIN_CHAT_ID, p['msg_id'], get_signal_keyboard(p['symbol'], p))
                        continue

                except Exception as inner_ex:
                    print(f"Inner monitor loop error for {p.get('symbol')}: {inner_ex}")

        except Exception as e:
            print(f"Monitor loop major error: {e}")
            time.sleep(5)

def automated_background_scanner():
    while True:
        try:
            time.sleep(1200)
            if ADMIN_CHAT_ID:
                scan_and_notify(ADMIN_CHAT_ID, notify_if_empty=False)
        except Exception as e:
            print(f"Background scanner error: {e}")
            time.sleep(60)

def start_telegram_bot():
    global ADMIN_CHAT_ID, ACTIVE_POSITIONS, TRADE_HISTORY, PAPER_BALANCE
    offset = 0
    print("Telegram/Bale bot polling loop started.")
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
                                if not ACTIVE_POSITIONS:
                                    send_bale_message(chat_id, "📈 در حال حاضر هیچ پوزیشن فعالی وجود ندارد.")
                                else:
                                    txt = "📈 پوزیشن‌های فعال دمو:\n"
                                    for p in ACTIVE_POSITIONS:
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

                            elif data_action.startswith('tp1_') or data_action.startswith('tp2_') or data_action.startswith('tp3_') or data_action.startswith('sl_'):
                                parts = data_action.split('_')
                                action_type = parts[0]
                                sym = parts[1]

                                for p in ACTIVE_POSITIONS:
                                    if p['symbol'] == sym:
                                        if action_type == 'tp1':
                                            p['hit_tp1'] = True
                                            p['sl'] = p['entry']
                                            p['risk_free'] = True
                                            pnl_manual = 15.0
                                            PAPER_BALANCE += pnl_manual
                                            TRADE_HISTORY.append({'symbol': sym, 'type': p['type'], 'pnl': pnl_manual})
                                            save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                                            edit_message_reply_markup(chat_id, message_id, get_signal_keyboard(sym, p))
                                            send_bale_message(chat_id, f"✅ TP1 برای {sym} تایید و سود پله اول ({pnl_manual:+.2f} $) واریز شد.")
                                        elif action_type == 'tp2':
                                            p['hit_tp2'] = True
                                            pnl_manual2 = 25.0
                                            PAPER_BALANCE += pnl_manual2
                                            TRADE_HISTORY.append({'symbol': sym, 'type': p['type'], 'pnl': pnl_manual2})
                                            save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                                            edit_message_reply_markup(chat_id, message_id, get_signal_keyboard(sym, p))
                                            send_bale_message(chat_id, f"✅ TP2 برای {sym} ثبت و سود ({pnl_manual2:+.2f} $) واریز شد.")
                                        elif action_type == 'tp3':
                                            curr_p = fetch_current_price(sym) or p['tp3']
                                            close_position_completely(p, curr_p, reason="هدف نهایی (TP3 دستی)")
                                            break
                                        elif action_type == 'sl':
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
                                    send_bale_message(chat_id, "🤖 پنل حساب دموی خودکار ربات\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=menu)
        except Exception as e:
            print(f"Telegram polling error: {e}")
            time.sleep(3)

if __name__ == '__main__':
    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
        except:
            pass

    threading.Thread(target=automated_price_monitor, daemon=True).start()
    threading.Thread(target=automated_background_scanner, daemon=True).start()
    threading.Thread(target=start_telegram_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
