
import asyncio, json, os, requests, threading, math, html
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

TELEGRAM_TOKEN = "8731559080:AAGGTxLogJIrQbGbNpY0_DMX854lu3fDp-0"
ARCGIS_URL = "https://services3.arcgis.com/MfVi0khS4tCyLmo3/arcgis/rest/services/Interventi_VVF_Assegnati_-_Ultime_6_ore/FeatureServer/0/query"
USERS_FILE = "users.json"

users = {}
app_ref = None

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return f"Bot VVF V5 FIX MARKDOWN - {len(users)} utenti"
def run_flask(): flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def save_users():
    try:
        data = {str(k): {"lat": v["lat"], "lon": v["lon"], "radius": v["radius"]} for k,v in users.items()}
        with open(USERS_FILE, "w") as f: json.dump(data, f)
    except Exception as e: print(f"save err {e}")

def load_users():
    global users
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                data = json.load(f)
                for k,v in data.items():
                    users[int(k)] = {"lat": v["lat"], "lon": v["lon"], "radius": v.get("radius",30000), "seen": set()}
            print(f"Caricati {len(users)} utenti")
        except Exception as e: print(f"load err {e}")

def haversine(lat1, lon1, lat2, lon2):
    R=6371000; p1=math.radians(lat1); p2=math.radians(lat2); dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

def query_all():
    params = {"f":"json","where":"1=1","outFields":"*","returnGeometry":"true","orderByFields":"OBJECTID DESC","resultRecordCount":100}
    try:
        r = requests.get(ARCGIS_URL, params=params, timeout=20)
        print(f"ArcGIS RAW status={r.status_code} len={len(r.text)}")
        print(f"ArcGIS RAW preview={r.text[:800]}")
        j = r.json()
        feats = j.get("features",[])
        if "error" in j: print(f"ArcGIS ERROR JSON: {j['error']}")
        print(f"ArcGIS ALL -> {len(feats)} interventi")
        return feats, r.status_code, j.get("error")
    except Exception as e:
        print(f"ArcGIS err {e}")
        return [], 0, str(e)

def get_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏙️ 5km", callback_data="raggio_5"), InlineKeyboardButton("🏘️ 10km", callback_data="raggio_10")],
        [InlineKeyboardButton("🚗 15km", callback_data="raggio_15"), InlineKeyboardButton("🚒 30km", callback_data="raggio_30")],
        [InlineKeyboardButton("🗺️ 50km", callback_data="raggio_50"), InlineKeyboardButton("🔇 Stop", callback_data="raggio_stop")],
        [InlineKeyboardButton("🧪 Test", callback_data="raggio_test"), InlineKeyboardButton("👀 Vicini ora", callback_data="raggio_vicini")]
    ])

async def check_all_users():
    if not app_ref: return
    result = await asyncio.to_thread(query_all)
    all_feats = result[0] if isinstance(result, tuple) else result
    if not all_feats: return
    for chat_id, u in list(users.items()):
        try:
            vicini = []
            for feat in all_feats:
                geom = feat.get("geometry",{})
                lat = geom.get("y"); lon = geom.get("x")
                if lat is None: continue
                dist = haversine(u["lat"], u["lon"], lat, lon)
                if dist <= u["radius"]: vicini.append((dist, feat))
            vicini.sort(key=lambda x: x[0])
            if len(u["seen"])==0 and len(vicini)>2:
                for d,f in vicini[2:]: u["seen"].add(f["attributes"].get("OBJECTID"))
                vicini = vicini[:2]
            for dist, feat in vicini:
                oid=feat["attributes"].get("OBJECTID")
                if oid in u["seen"]: continue
                u["seen"].add(oid)
                attr=feat.get("attributes",{}); tip=str(attr.get("TIPOLOGIA") or "VVF"); sotto=str(attr.get("SOTTOTIPOLOGIA") or ""); comune=str(attr.get("COMUNE") or ""); indir=str(attr.get("INDIRIZZO") or ""); data=str(attr.get("DATA_SEGNALAZIONE") or "")[:16]
                lat=feat.get("geometry",{}).get("y"); lon=feat.get("geometry",{}).get("x")
                dist_txt=f"{dist/1000:.1f}km" if dist>=1000 else f"{int(dist)}m"
                maps_url=f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                # Messaggio SENZA markdown rischioso, uso HTML safe
                msg=f"🚨 NUOVO VVF!\n{tip} {sotto}\n{comune} {indir}\n{data}\n{dist_txt} entro {int(u['radius']/1000)}km"
                kb=InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Maps", url=maps_url)]])
                await app_ref.bot.send_message(chat_id=chat_id, text=msg, reply_markup=kb)
        except Exception as e: print(f"check err {e}")

async def background_loop():
    await asyncio.sleep(10)
    while True:
        await check_all_users()
        await asyncio.sleep(60)

async def handle_loc(update, context):
    msg = update.message or update.edited_message
    if not msg or not msg.location: return
    chat_id = update.effective_chat.id
    loc = msg.location
    if chat_id not in users: users[chat_id] = {"lat": loc.latitude, "lon": loc.longitude, "radius": 30000, "seen": set()}
    else: users[chat_id]["lat"]=loc.latitude; users[chat_id]["lon"]=loc.longitude
    save_users()
    if update.message:
        await msg.reply_text(f"✅ LIVE salvata! {loc.latitude:.5f},{loc.longitude:.5f} raggio {int(users[chat_id]['radius']/1000)}km", reply_markup=get_keyboard())
        await show_vicini(update, context, False)

async def show_vicini(update, context, silent=True):
    chat_id = update.effective_chat.id
    u = users.get(chat_id)
    if not u: return
    result = await asyncio.to_thread(query_all)
    feats = result[0]
    vicini=[]
    for f in feats:
        g=f.get("geometry",{}); lat=g.get("y"); lon=g.get("x")
        if lat is None: continue
        d=haversine(u["lat"], u["lon"], lat, lon)
        if d <= u["radius"]: vicini.append((d,f))
    vicini.sort(key=lambda x: x[0])
    if not vicini:
        txt=f"👀 Nessun intervento entro {int(u['radius']/1000)}km ultime 6h. Tot Piemonte: {len(feats)}"
        if update.callback_query: 
            try: await update.callback_query.edit_message_text(txt, reply_markup=get_keyboard())
            except: await context.bot.send_message(chat_id=chat_id, text=txt, reply_markup=get_keyboard())
        else: await context.bot.send_message(chat_id=chat_id, text=txt, reply_markup=get_keyboard())
        return
    for d,f in vicini[:5]:
        attr=f.get("attributes",{}); tip=str(attr.get("TIPOLOGIA") or "VVF"); sotto=str(attr.get("SOTTOTIPOLOGIA") or ""); comune=str(attr.get("COMUNE") or ""); indir=str(attr.get("INDIRIZZO") or ""); data=str(attr.get("DATA_SEGNALAZIONE") or "")[:16]
        lat=f.get("geometry",{}).get("y"); lon=f.get("geometry",{}).get("x")
        maps_url=f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        msg=f"👀 Vicino ORA {d/1000:.1f}km\n{tip} {sotto}\n{comune} {indir}\n{data}"
        await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Maps", url=maps_url)]]))

async def start_cmd(update, context):
    await update.message.reply_text("🚒 Bot VVF V5 FIX - niente piu errori markdown\n/vicini - vedi ora\n/stato - debug\n/test - test", reply_markup=get_keyboard())

async def stato_cmd(update, context):
    u=users.get(update.effective_chat.id)
    if not u: await update.message.reply_text("Non registrato. Invia posizione Live."); return
    result = await asyncio.to_thread(query_all)
    feats, status, err = result
    vicini=sum(1 for f in feats if f.get("geometry",{}).get("y") and haversine(u["lat"], u["lon"], f["geometry"]["y"], f["geometry"]["x"]) <= u["radius"])
    # NIENTE MARKDOWN QUI - testo semplice
    txt=f"DEBUG V5\nHTTP: {status}\nErr: {err}\nTot 6h Piemonte: {len(feats)}\nEntro {int(u['radius']/1000)}km: {vicini}\nVisti: {len(u['seen'])}"
    if feats:
        f=feats[0]; attr=f.get("attributes",{})
        txt+=f"\n\nUltimo: {attr.get('COMUNE')} {attr.get('TIPOLOGIA')} {str(attr.get('DATA_SEGNALAZIONE'))[:16]}"
    # Invio SENZA parse_mode per evitare BadRequest
    await update.message.reply_text(txt)

async def test_cmd(update, context):
    chat_id=update.effective_chat.id
    u=users.get(chat_id)
    if not u: await update.message.reply_text("Prima LIVE"); return
    await context.bot.send_message(chat_id=chat_id, text=f"TEST OK raggio {int(u['radius']/1000)}km!", reply_markup=get_keyboard())

async def raggio_cb(update, context):
    q=update.callback_query
    try: await q.answer()
    except: pass
    chat_id=update.effective_chat.id; data=q.data; print(f"CB {chat_id} -> {data}")
    if data=="raggio_test": await test_cmd(update, context); return
    if data=="raggio_vicini": await show_vicini(update, context, False); return
    if data=="raggio_stop":
        if chat_id in users: del users[chat_id]; save_users()
        try: await q.edit_message_text("Stop")
        except: pass
        return
    if chat_id not in users: 
        try: await q.edit_message_text("Prima LIVE!")
        except: pass
        return
    km=int(data.split("_")[1]); users[chat_id]["radius"]=km*1000; save_users()
    try: await q.edit_message_text(f"Raggio {km}km! Cerco...", reply_markup=get_keyboard())
    except: pass
    await show_vicini(update, context, False)

async def post_init(app):
    global app_ref
    try: await app.bot.delete_webhook(drop_pending_updates=True); print("Webhook deleted")
    except Exception as e: print(f"del webhook err {e}")
    app_ref=app; asyncio.create_task(background_loop())

def main():
    load_users()
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    threading.Thread(target=run_flask, daemon=True).start()
    app=ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CommandHandler("stato", stato_cmd))
    app.add_handler(CommandHandler("vicini", lambda u,c: show_vicini(u,c,False)))
    app.add_handler(MessageHandler(filters.LOCATION, handle_loc))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & filters.LOCATION, handle_loc))
    app.add_handler(CallbackQueryHandler(raggio_cb, pattern="^raggio_"))
    print(f"Avviato V5 FIX MARKDOWN - {len(users)} utenti")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message","edited_message","callback_query"])

if __name__=="__main__": main()
