(
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
            log_error_to_bale(f"Monit
