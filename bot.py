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

ADMIN_CHAT_ID = 2125586940

DEFAULT_MARGIN = 15.0
LEVERAGE = 10
INITIAL_BALANCE = 100.0
FEE_RATE = 0.0005

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running perfectly!", 200

def load_database():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            saved_admin = data.get('admin_id')
            final_admin = saved_admin if saved_admin else ADMIN_CHAT_ID
            return data.get('active', []), data.get('history', []), final_admin, data.get('balance', INITIAL_BALANCE)
        except Exception as e:
            print(f"DB Load Error: {e}")
    return [], [], ADMIN_CHAT_ID, INITIAL_BALANCE

def save_database(active, history, admin_id, balance):
    try:
        data = {'active': active, 'history': history, 'admin_id': admin_id, 'balance': balance}
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"DB Save Error: {e}")

ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE = load_database()

def get_current_admin_chat_id():
    _, _, current_admin, _ = load_database()
    return current_admin or ADMIN_CHAT_ID

def send_bale_message(chat_id, text, reply_markup=None, reply_to_message_id=None):
    target_chat = chat_id or get_current_admin_chat_id()
    if not target_chat:
        print("Error: target_chat is empty!")
        return None
    url = f"{BASE_URL}/sendMessage"
    payload = {'chat_id': target_chat, 'text': text}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id
    try:
        response = requests.post(url, json=payload, timeout=15, verify=False)
        print(f"--> Bale Send Response Code: {response.status_code}, Text: {response.text}")
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"--> Send Message Exception: {e}")
    return None

def edit_message_reply_markup(chat_id, message_id, reply_markup):
    target_chat = chat_id or get_current_admin_chat_id()
    if not target_chat or not message_id:
        return
    url = f"{BASE_URL}/editMessageReplyMarkup"
    payload = {'chat_id': target_chat, 'message_id': message_id, 'reply_markup': reply_markup}
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
            [{"text": "⚙️ وضعیت سیستم", "callback_data": "bot_status"}, {"text": "🧪 تست سیگنال دستی", "callback_data": "test_signal"}],
            [{"text": "🔄 ریست کامل حساب", "callback_data": "reset_stats"}]
        ]
    }

def get_signal_keyboard(symbol, p_data=None):
    t1 = "✅ TP1 (لمس شد)" if (p_data and p_data.get('hit_tp1')) else "🎯 TP1"
    t2 = "✅ TP2 (لمس شد)" if (p_data and p_data.get('hit_tp2')) else "🎯 TP2"
    t3 = "✅ TP3 (لمس شد)" if (p_data and p_data.get('hit_tp3')) else "🎯 TP3"
    sl_text = "❌ SL (لمس شد)" if (p_data and p_data.get('hit_sl')) else "🛑 ثبت لمس SL"
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
            df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'q_vol', 'trades', 't_buy_base', 't_buy_quote'])
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['open'] = df['open'].astype(float)
            df['volume'] = df['volume'].astype(float)
            return df
    except Exception as e:
        pass
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
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def analyze_and_open_position(symbol):
    global ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE
    if any(p['symbol'] == symbol for p in ACTIVE_POSITIONS):
        return False

    df = fetch_historical_candles(symbol, "15m", 100)
    if df is None or len(df) < 40:
        return False

    df = calculate_indicators(df)
    last = df.iloc[-1]
    price = last['close']
    ema20 = last['ema20']
    ema50 = last['ema50']
    volume = last['volume']
    vol_ma20 = last['vol_ma20']
    rsi = last['rsi']

    signal_type = None
    if ema20 > ema50 and rsi < 70 and (not pd.isna(vol_ma20) and volume >= vol_ma20 * 1.2):
        signal_type = 'LONG'
    elif ema20 < ema50 and rsi > 30 and (not pd.isna(vol_ma20) and volume >= vol_ma20 * 1.2):
        signal_type = 'SHORT'

    if not signal_type:
        return False

    if signal_type == 'LONG':
        sl = price * 0.985
        tp1 = price * 1.012
        tp2 = price * 1.025
        tp3 = price * 1.040
    else:
        sl = price * 1.015
        tp1 = price * 0.988
        tp2 = price * 0.975
        tp3 = price * 0.960

    open_fee = (DEFAULT_MARGIN * LEVERAGE) * FEE_RATE
    PAPER_BALANCE -= open_fee

    pos = {
        'symbol': symbol, 'type': signal_type, 'entry': price, 'sl': sl,
        'tp1': tp1, 'tp2': tp2, 'tp3': tp3, 'margin': DEFAULT_MARGIN, 'status': 'ACTIVE',
        'hit_tp1': False, 'hit_tp2': False, 'hit_tp3': False, 'hit_sl': False, 'risk_free': False,
        'msg_id': None
    }
    ACTIVE_POSITIONS.append(pos)
    target_admin = get_current_admin_chat_id()
    save_database(ACTIVE_POSITIONS, TRADE_HISTORY, target_admin, PAPER_BALANCE)

    icon = "🚀" if signal_type == 'LONG' else "📉"
    decimals = 8 if price < 1 else 4
    fmt = f"{{:.{decimals}f}}"

    msg = (
        f"{icon} سیگنال هوشمند جدید\n"
        f"──────────────────────\n"
        f"🔹 نماد: {symbol} ({signal_type})\n"
        f"💵 قیمت ورود: {price:{fmt}}\n"
        f"💰 مارجین: {DEFAULT_MARGIN}$\n"
        f"🎯 TP1: {tp1:{fmt}}\n"
        f"🎯 TP2: {tp2:{fmt}}\n"
        f"🎯 TP3: {tp3:{fmt}}\n"
        f"🛑 SL: {sl:{fmt}}\n"
        f"──────────────────────"
    )
    
    print(f"Attempting to send signal for {symbol} to chat_id: {target_admin}")
    res = send_bale_message(target_admin, msg, reply_markup=get_signal_keyboard(symbol, pos))
    try:
        if res and 'result' in res:
            pos['msg_id'] = res['result']['message_id']
            save_database(ACTIVE_POSITIONS, TRADE_HISTORY, target_admin, PAPER_BALANCE)
    except Exception as e:
        print(f"Error saving msg_id: {e}")

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
    target_admin = get_current_admin_chat_id()

    p['hit_sl'] = True
    if p.get('msg_id') and target_admin:
        edit_message_reply_markup(target_admin, p['msg_id'], get_signal_keyboard(p['symbol'], p))

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

    save_database(ACTIVE_POSITIONS, TRADE_HISTORY, target_admin, PAPER_BALANCE)

    decimals = 8 if entry < 1 else 4
    fmt = f"{{:.{decimals}f}}"

    report_text = (
        f"📢 گزارش بسته شدن معامله\n"
        f"──────────────────────\n"
        f"🔹 نماد: {p['symbol']} ({position_type})\n"
        f"💵 قیمت ورود: {entry:{fmt}}\n"
        f"🏁 قیمت خروج ({reason}): {exit_price:{fmt}}\n"
        f"💰 سود / زیان خالص: {net_pnl:+.2f} $\n"
        f"💳 موجودی جدید حساب دمو: {PAPER_BALANCE:.2f} $\n"
        f"──────────────────────"
    )
    if target_admin:
        send_bale_message(target_admin, report_text, reply_to_message_id=p.get('msg_id'))

def periodic_auto_scanner():
    symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", 
        "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
        "LTCUSDT", "NEARUSDT", "ATOMUSDT", "UNIUSDT", "APTUSDT"
    ]
    while True:
        try:
            for sym in symbols:
                analyze_and_open_position(sym)
                time.sleep(1)
            time.sleep(120)
        except Exception as e:
            print(f"Scanner Error: {e}")
            time.sleep(30)

def automated_price_monitor():
    while True:
        try:
            time.sleep(5)
            if not ACTIVE_POSITIONS: continue
            target_admin = get_current_admin_chat_id()
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
                        close_position_completely(p, p['sl'], reason="SL")
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
                        save_database(ACTIVE_POSITIONS, TRADE_HISTORY, target_admin, PAPER_BALANCE)
                        
                        if p.get('msg_id') and target_admin:
                            edit_message_reply_markup(target_admin, p['msg_id'], get_signal_keyboard(p['symbol'], p))
                        
                        msg_tp1 = f"🎯 هدف اول (TP1) برای {p['symbol']} لمس شد!\n💰 سود پله اول ({net_part:+.2f} $) واریز شد.\n🛡 SL به نقطه ورود منتقل شد."
                        if target_admin: send_bale_message(target_admin, msg_tp1, reply_to_message_id=p.get('msg_id'))
                        continue

                    hit_tp2_cond = (p_type == 'LONG' and curr >= p['tp2']) or (p_type == 'SHORT' and curr <= p['tp2'])
                    if hit_tp2_cond and not p.get('hit_tp2', False):
                        p['hit_tp2'] = True
                        pnl_part = calculate_pnl(entry, p['tp2'], p_type, margin, LEVERAGE) * 0.3
                        fee_part = (margin * LEVERAGE * 0.3) * FEE_RATE
                        net_part = pnl_part - fee_part
                        PAPER_BALANCE += net_part
                        TRADE_HISTORY.append({'symbol': p['symbol'], 'type': p_type, 'pnl': net_part})
                        save_database(ACTIVE_POSITIONS, TRADE_HISTORY, target_admin, PAPER_BALANCE)
                        
                        if p.get('msg_id') and target_admin:
                            edit_message_reply_markup(target_admin, p['msg_id'], get_signal_keyboard(p['symbol'], p))
                        
                        msg_tp2 = f"🎯 هدف دوم (TP2) برای {p['symbol']} لمس شد!\n💰 سود پله دوم ({net_part:+.2f} $) واریز شد."
                        if target_admin: send_bale_message(target_admin, msg_tp2, reply_to_message_id=p.get('msg_id'))
                        continue

                    hit_tp3_cond = (p_type == 'LONG' and curr >= p['tp3']) or (p_type == 'SHORT' and curr <= p['tp3'])
                    if hit_tp3_cond and not p.get('hit_tp3', False):
                        p['hit_tp3'] = True
                        p['hit_tp1'] = True
                        p['hit_tp2'] = True
                        
                        if p.get('msg_id') and target_admin:
                            edit_message_reply_markup(target_admin, p['msg_id'], get_signal_keyboard(p['symbol'], p))
                        
                        pnl_part = calculate_pnl(entry, p['tp3'], p_type, margin, LEVERAGE) * 0.3
                        fee_part = (margin * LEVERAGE * 0.3) * FEE_RATE
                        net_part = pnl_part - fee_part
                        PAPER_BALANCE += net_part
                        TRADE_HISTORY.append({'symbol': p['symbol'], 'type': p_type, 'pnl': net_part})
                        
                        p['status'] = 'CLOSED'
                        p['exit_price'] = p['tp3']
                        if p in ACTIVE_POSITIONS:
                            ACTIVE_POSITIONS.remove(p)
                        save_database(ACTIVE_POSITIONS, TRADE_HISTORY, target_admin, PAPER_BALANCE)
                        
                        msg_tp3 = f"🏆 هدف نهایی (TP3) برای {p['symbol']} کامل شد!\n💰 سود پله سوم ({net_part:+.2f} $) و معامله بسته شد."
                        if target_admin: send_bale_message(target_admin, msg_tp3, reply_to_message_id=p.get('msg_id'))
                        continue

                except Exception as inner_ex:
                    pass
        except Exception as e:
            time.sleep(5)

def start_telegram_bot():
    global ADMIN_CHAT_ID, ACTIVE_POSITIONS, TRADE_HISTORY, PAPER_BALANCE
    offset = 0
    print("Telegram bot polling started...")
    while True:
        try:
            url = f"{BASE_URL}/getUpdates?offset={offset}&timeout=20"
            response = requests.get(url, timeout=25, verify=False)
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    for update in data['result']:
                        offset = update['update_id'] + 1

                        if 'message' in update:
                            msg = update['message']
                            if 'chat' in msg:
                                ADMIN_CHAT_ID = msg['chat']['id']
                                save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

                        if 'callback_query' in update:
                            cq = update['callback_query']
                            chat_id = cq['message']['chat']['id']
                            ADMIN_CHAT_ID = chat_id
                            message_id = cq['message']['message_id']
                            data_action = cq['data']
                            answer_callback_query(cq['id'], "انجام شد ✓")
                            save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)

                            if data_action == 'active_positions':
                                if not ACTIVE_POSITIONS:
                                    send_bale_message(chat_id, "📈 در حال حاضر هیچ پوزیشن فعالی وجود ندارد.")
                                else:
                                    txt = "📈 پوزیشن‌های فعال دمو:\n"
                                    for p in ACTIVE_POSITIONS:
                                        dec = 8 if p['entry'] < 1 else 4
                                        txt += f"- {p['symbol']} ({p['type']}) | ورود: {p['entry']:.{dec}f} | مارجین: {p.get('margin', DEFAULT_MARGIN)}$\n"
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
                                    f"🎯 کل معاملات: {total_trades}\n"
                                    f"✅ موفق: {wins} | ❌ ناموفق: {losses}\n"
                                    f"📈 درصد وین‌ریت: {win_rate:.1f}%\n"
                                    f"💰 سود/زیان خالص: {total_pnl:+.2f} $\n"
                                    f"──────────────────────"
                                )
                                send_bale_message(chat_id, stats_txt)
                            elif data_action == 'bot_status':
                                status_msg = (
                                    f"⚙ وضعیت سیستم ربات:\n"
                                    f"• حالت کاری: استراتژی هوشمند فیلتر‌شده (RSI + Volume)\n"
                                    f"• تایم‌فریم: ۱۵ دقیقه\n"
                                    f"• مانیتورینگ قیمت: فعال\n"
                                    f"• مارجین: {DEFAULT_MARGIN}$ | اهرم: {LEVERAGE}x"
                                )
                                send_bale_message(chat_id, status_msg)
                            elif data_action == 'test_signal':
                                test_sym = "BTCUSDT"
                                test_msg = (
                                    "🚀 تست سیگنال دستی\n"
                                    "──────────────────────\n"
                                    "🔹 نماد: BTCUSDT (LONG)\n"
                                    "💵 قیمت ورود: 60000\n"
                                    "💰 مارجین: 15.0$\n"
                                    "🎯 TP1: 60720\n"
                                    "🎯 TP2: 61500\n"
                                    "🎯 TP3: 62400\n"
                                    "🛑 SL: 59100\n"
                                    "──────────────────────"
                                )
                                print("--> Triggering test_signal manually...")
                                send_bale_message(chat_id, test_msg, reply_markup=get_signal_keyboard(test_sym))
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
                                            send_bale_message(chat_id, f"✅ TP1 برای {sym} ثبت و سود پله اول ({net_m:+.2f} $) واریز شد.", reply_to_message_id=p.get('msg_id'))
                                        elif action_type == 'tp2':
                                            p['hit_tp2'] = True
                                            pnl_manual = calculate_pnl(p['entry'], p['tp2'], p['type'], margin, LEVERAGE) * 0.3
                                            fee_m = (margin * LEVERAGE * 0.3) * FEE_RATE
                                            net_m = pnl_manual - fee_m
                                            PAPER_BALANCE += net_m
                                            TRADE_HISTORY.append({'symbol': sym, 'type': sym, 'pnl': net_m})
                                            save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                                            edit_message_reply_markup(chat_id, message_id, get_signal_keyboard(sym, p))
                                            send_b_message(chat_id, f"✅ TP2 برای {sym} ثبت و سود پله دوم ({net_m:+.2f} $) واریز شد.", reply_to_message_id=p.get('msg_id'))
                                        elif action_type == 'tp3':
                                            p['hit_tp3'] = True
                                            p['hit_tp1'] = True
                                            p['hit_tp2'] = True
                                            edit_message_reply_markup(chat_id, message_id, get_signal_keyboard(sym, p))
                                            close_position_completely(p, p['tp3'], reason="TP3 دستی")
                                            break
                                        elif action_type == 'sl':
                                            close_position_completely(p, p['sl'], reason="SL دستی")
                                            break

                        elif 'message' in update:
                            msg = update['message']
                            if 'text' in msg:
                                chat_id = msg['chat']['id']
                                ADMIN_CHAT_ID = chat_id
                                save_database(ACTIVE_POSITIONS, TRADE_HISTORY, ADMIN_CHAT_ID, PAPER_BALANCE)
                                text = msg['text'].strip()

                                if text == '/start':
                                    menu = get_main_menu_keyboard()
                                    send_bale_message(chat_id, "🤖 ربات فعال است. لطفاً از منوی زیر استفاده کنید:", reply_markup=menu)
            else:
                pass
        except Exception as e:
            print(f"Telegram Polling Error: {e}")
            time.sleep(3)

if __name__ == '__main__':
    threading.Thread(target=automated_price_monitor, daemon=True).start()
    threading.Thread(target=periodic_auto_scanner, daemon=True).start()
    threading.Thread(target=start_telegram_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
