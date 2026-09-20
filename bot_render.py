import asyncio, json, os, requests, threading, math
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

TELEGRAM_TOKEN = "8731559080:AAGGTxLogJIrQbGbNpY0_DMX854lu3fDp-0"
ARCGIS_URL = "https://services3.arcgis.com/MfVi0khS4tCyLmo3/arcgis/rest/services/Interventi_VVF_Assegnati_-_Ultime_6_ore/FeatureServer/0/query"
TOKEN_URL = "https://www.arcgis.com/sharing/rest/generateToken"
USERS_FILE = "users.json"

users = {}
app_ref = None
arcgis_token = None
arcgis_token_exp = 0

flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return f"Bot VVF V6 - {len(users)} utenti"
def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def save_users():
    try:
        data = {str(k): {"lat": v["lat"], "lon": v["lon"], "radius": v["radius"]} for k,v in users.items()}
        with open(USERS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"save err {e}")

def load_users():
    global users
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                data = json.load(f)
                for k,v in data.items():
                    users[int(k)] = {"lat": v["lat"], "lon": v["lon"], "radius": v.get("radius",30000), "seen": set()}
            print(f"Caricati {len(users)} utenti")
        except Exception as e:
            print(f"load err {e}")

def haversine(lat1, lon1, lat2, lon2):
    R=6371000
    p1=math.radians(lat1)
    p2=math.radians(lat2)
    dlat=math.radians(lat2-lat1)
    dlon=math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

def get_arcgis_token():
    global arcgis_token, arcgis_token_exp
    import time
    if arcgis_token and time.time() < arcgis_token_exp - 60:
        return arcgis_token
    try:
        data = {"f": "json", "referer": "https://www.arcgis.com", "expiration": "60"}
        r = requests.post(TOKEN_URL, data=data, timeout=10)
        print(f"TOKEN status={r.status_code} {r.text[:500]}")
        j = r.json()
        tok = j.get("token")
        if tok:
            arcgis_token = tok
            arcgis_token_exp = time.time() + 55*60
            return tok
    except Exception as e:
        print(f"get token err {e}")
    return None

def query_all():
    tok = get_arcgis_token()
    params = {"f":"json","where":"1=1","outFields":"*","returnGeometry":"true","orderByFields":"OBJECTID DESC","resultRecordCount":100}
    if tok:
        params["token"] = tok
    try:
        r = requests.get(ARCGIS_URL, params=params, timeout=20)
        print(f"ArcGIS RAW status={r.status_code} len={len(r.text)}")
        print(f"ArcGIS RAW preview={r.text[:800]}")
        j = r.json()
        feats = j.get("features",[])
        print(f"ArcGIS ALL -> {len(feats)} interventi")
        return feats, r.status_code, j.get("error")
    except Exception as e:
        print(f"ArcGIS err {e}")
        return [], 0, str(e)

def get_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5km", callback_data="raggio_5"), InlineKeyboardButton("10km", callback_data="raggio_10")],
        [InlineKeyboardButton("15km", callback_data="raggio_15"), InlineKeyboardButton("30km", callback_data="raggio_30")],
        [InlineKeyboardButton("50km", callback_data="raggio_50"), InlineKeyboardButton("Stop", callback_data="raggio_stop")],
        [InlineKeyboardButton("Test", callback_data="raggio_test"), InlineKeyboardButton("Vicini ora", callback_data="raggio_vicini")]
    ])

async def check_all_users():
    if not app_ref:
        return
    result = await asyncio.to_thread(query_all)
    all_feats = result[0]
    if not all_feats:
        return
    for chat_id, u in list(users.items()):
        try:
            vicini = []
            for feat in all_feats:
                geom = feat.get("geometry",{})
                lat = geom.get("y")
                lon = geom.get("x")
                if lat is None:
                    continue
                dist = haversine(u["lat"], u["lon"], lat, lon)
                if dist <= u["radius"]:
                    vicini.append((dist, feat))
            vicini.sort(key=lambda x: x[0])
            if len(u["seen"])==0 and len(vicini)>2:
                for d,f in vicini[2:]:
                    u["seen"].add(f["attributes"].get("OBJECTID"))
                vicini = vicini[:2]
            for dist, feat in vicini:
                oid=feat["attributes"].get("OBJECTID")
                if oid in u["seen"]:
                    continue
                u["seen"].add(oid)
                attr=feat.get("attributes",{})
                tip=str(attr.get("TIPOLOGIA") or "VVF")
                sotto=str(attr.get("SOTTOTIPOLOGIA") or "")
                comune=str(attr.get("COMUNE") or "")
                indir=str(attr.get("INDIRIZZO") or "")
                data=str(attr.get("DATA_SEGNALAZIONE") or "")[:16]
                lat=feat.get("geometry",{}).get("y")
                lon=feat.get("geometry",{}).get("x")
                maps_url=f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                msg=f"NUOVO VVF!\n{tip} {sotto}\n{comune} {indir}\n{data}\n{int(dist)}m entro {int(u['radius']/1000)}km"
                kb=InlineKeyboardMarkup([[InlineKeyboardButton("Maps", url=maps_url)]])
                await app_ref.bot.send_message(chat_id=chat_id, text=msg, reply_markup=kb)
        except Exception as e:
            print(f"check err {e}")

async def background_loop():
    await asyncio.sleep(10)
    while True:
        await check_all_users()
        await asyncio.sleep(60)

async def handle_loc(update, context):
    msg = update.message or update.edited_message
    if not msg or not msg.location:
        return
    chat_id = update.effective_chat.id
    loc = msg.location
    if chat_id not in users:
        users[chat_id] = {"lat": loc.latitude, "lon": loc.longitude, "radius": 30000, "seen": set()}
    else:
        users[chat_id]["lat"]=loc.latitude
        users[chat_id]["lon"]=loc.longitude
    save_users()
    if update.message:
        await msg.reply_text(f"LIVE salvata! raggio {int(users[chat_id]['radius']/1000)}km", reply_markup=get_keyboard())

async def stato_cmd(update, context):
    u=users.get(update.effective_chat.id)
    if not u:
        await update.message.reply_text("Non registrato. Invia posizione Live.")
        return
    result = await asyncio.to_thread(query_all)
    feats, status, err = result
    txt=f"DEBUG V6\nHTTP: {status}\nErr: {err}\nTot Piemonte: {len(feats)}"
    if feats:
        f=feats[0]
        attr=f.get("attributes",{})
        txt+=f"\nUltimo: {attr.get('COMUNE')} {attr.get('TIPOLOGIA')}"
    await update.message.reply_text(txt)

async def start_cmd(update, context):
    await update.message.reply_text("Bot VVF V6 - /stato per debug", reply_markup=get_keyboard())

async def raggio_cb(update, context):
    q=update.callback_query
    try:
        await q.answer()
    except:
        pass
    chat_id=update.effective_chat.id
    data=q.data
    if data=="raggio_stop":
        if chat_id in users:
            del users[chat_id]
            save_users()
        await q.edit_message_text("Stop")
        return
    if chat_id not in users:
        await q.edit_message_text("Prima LIVE!")
        return
    if data.startswith("raggio_"):
        try:
            km=int(data.split("_")[1])
            users[chat_id]["radius"]=km*1000
            save_users()
            await q.edit_message_text(f"Raggio {km}km!", reply_markup=get_keyboard())
        except:
            pass

async def post_init(app):
    global app_ref
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except:
        pass
    app_ref=app
    asyncio.create_task(background_loop())

def main():
    load_users()
    threading.Thread(target=run_flask, daemon=True).start()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app=ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stato", stato_cmd))
    app.add_handler(MessageHandler(filters.LOCATION, handle_loc))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & filters.LOCATION, handle_loc))
    app.add_handler(CallbackQueryHandler(raggio_cb, pattern="^raggio_"))
    print(f"Avviato V6 - {len(users)} utenti")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message","edited_message","callback_query"])

if __name__=="__main__":
    main()
