
import asyncio, json, os, requests, threading, math
from datetime import datetime
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
def home(): return f"Bot VVF V3 - {len(users)} utenti - fix raggio"
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

def query_all_interventions():
    # Prende TUTTI gli interventi ultime 6h senza filtro spaziale, poi filtriamo noi
    params = {"f":"json","where":"1=1","outFields":"*","returnGeometry":"true","orderByFields":"OBJECTID DESC","resultRecordCount":100}
    try:
        r = requests.get(ARCGIS_URL, params=params, timeout=20)
        feats = r.json().get("features",[])
        print(f"ArcGIS ALL -> {len(feats)} interventi totali ultime 6h")
        return feats
    except Exception as e:
        print(f"ArcGIS ALL err {e}"); return []

def get_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏙️ 5km", callback_data="raggio_5"), InlineKeyboardButton("🏘️ 10km", callback_data="raggio_10")],
        [InlineKeyboardButton("🚗 15km", callback_data="raggio_15"), InlineKeyboardButton("🚒 30km", callback_data="raggio_30")],
        [InlineKeyboardButton("🗺️ 50km", callback_data="raggio_50"), InlineKeyboardButton("🔇 Stop", callback_data="raggio_stop")],
        [InlineKeyboardButton("🧪 Test", callback_data="raggio_test"), InlineKeyboardButton("👀 Vicini ora", callback_data="raggio_vicini")]
    ])

async def check_all_users():
    if not app_ref: return
    all_feats = await asyncio.to_thread(query_all_interventions)
    if not all_feats: return
    for chat_id, u in list(users.items()):
        try:
            vicini = []
            for feat in all_feats:
                geom = feat.get("geometry",{})
                lat = geom.get("y"); lon = geom.get("x")
                if lat is None or lon is None: continue
                dist = haversine(u["lat"], u["lon"], lat, lon)
                if dist <= u["radius"]:
                    vicini.append((dist, feat))
            vicini.sort(key=lambda x: x[0])
            # Se è primo avvio, segna tutti come visti tranne i 2 più vicini per non spammare ma far vedere qualcosa
            if len(u["seen"])==0 and len(vicini)>2:
                for d,f in vicini[2:]:
                    u["seen"].add(f["attributes"].get("OBJECTID"))
                vicini = vicini[:2]
            for dist, feat in vicini:
                attr=feat.get("attributes",{}); oid=attr.get("OBJECTID")
                if oid in u["seen"]: continue
                u["seen"].add(oid)
                tip=attr.get("TIPOLOGIA") or "Intervento VVF"; sotto=attr.get("SOTTOTIPOLOGIA") or ""; comune=attr.get("COMUNE") or ""; indir=attr.get("INDIRIZZO") or attr.get("LOCALITA") or ""; data=attr.get("DATA_SEGNALAZIONE") or ""; data_str=str(data)[:16] if data else ""
                lat=feat.get("geometry",{}).get("y"); lon=feat.get("geometry",{}).get("x")
                dist_txt=f"{dist/1000:.1f}km" if dist>=1000 else f"{int(dist)}m"
                maps_url=f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                msg=f"🚨 *NUOVO INTERVENTO VVF!* 🚒\n\n📋 *{tip}*"
                if sotto: msg+=f" - {sotto}"
                msg+=f"\n📍 *{comune}* {indir}\n🕐 {data_str}\n📏 {dist_txt} da te (entro {int(u['radius']/1000)}km)"
                kb=InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Naviga con Maps", url=maps_url)]])
                await app_ref.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown", reply_markup=kb)
                print(f"Inviato {oid} a {chat_id} - {dist_txt}")
        except Exception as e: print(f"check {chat_id} err {e}")

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
    if chat_id not in users:
        users[chat_id] = {"lat": loc.latitude, "lon": loc.longitude, "radius": 30000, "seen": set()}
    else:
        users[chat_id]["lat"] = loc.latitude; users[chat_id]["lon"] = loc.longitude
    save_users()
    if update.message:
        await msg.reply_text(f"✅ Posizione LIVE salvata!\n📍 {loc.latitude:.5f}, {loc.longitude:.5f}\nRaggio: {int(users[chat_id]['radius']/1000)}km\n\nOra cerco tutti gli interventi vicini...", reply_markup=get_keyboard())
        await show_vicini(update, context, silent=False)

async def show_vicini(update, context, silent=True):
    chat_id = update.effective_chat.id
    u = users.get(chat_id)
    if not u:
        if not silent: await update.message.reply_text("Prima invia posizione Live!")
        return
    feats = await asyncio.to_thread(query_all_interventions)
    vicini = []
    for feat in feats:
        geom=feat.get("geometry",{}); lat=geom.get("y"); lon=geom.get("x")
        if lat is None: continue
        d=haversine(u["lat"], u["lon"], lat, lon)
        if d <= u["radius"]: vicini.append((d, feat))
    vicini.sort(key=lambda x: x[0])
    if not vicini:
        txt=f"👀 Nessun intervento nelle ultime 6h entro {int(u['radius']/1000)}km da te.\nTotale in Piemonte ultime 6h: {len(feats)}\nTutto tranquillo! ✅"
        if update.callback_query:
            await update.callback_query.edit_message_text(txt, reply_markup=get_keyboard())
        else:
            await context.bot.send_message(chat_id=chat_id, text=txt, reply_markup=get_keyboard())
        return
    # Mostra fino a 5 più vicini
    for d, feat in vicini[:5]:
        attr=feat.get("attributes",{}); tip=attr.get("TIPOLOGIA") or "VVF"; sotto=attr.get("SOTTOTIPOLOGIA") or ""; comune=attr.get("COMUNE") or ""; indir=attr.get("INDIRIZZO") or ""; data=attr.get("DATA_SEGNALAZIONE") or ""; data_str=str(data)[:16] if data else ""
        lat=feat.get("geometry",{}).get("y"); lon=feat.get("geometry",{}).get("x")
        dist_txt=f"{d/1000:.1f}km" if d>=1000 else f"{int(d)}m"
        maps_url=f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        msg=f"👀 *Intervento vicino ORA*\n📋 *{tip}* {sotto}\n📍 {comune} {indir}\n🕐 {data_str}\n📏 {dist_txt} (entro {int(u['radius']/1000)}km)"
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Maps", url=maps_url)]])
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown", reply_markup=kb)

async def start_cmd(update, context):
    chat_id = update.effective_chat.id
    if chat_id in users:
        stato=f"✅ Attiva - raggio {int(users[chat_id]['radius']/1000)}km - {len(users[chat_id]['seen'])} visti"
    else:
        stato="⚠️ Non hai ancora inviato posizione Live"
    await update.message.reply_text(f"🚒 *Bot VVF V3 - FIX RAGGIO*\n\n{stato}\n\nComandi:\n/vicini - vedi subito cosa c'è ora vicino a te\n/test - prova notifica\n/stato - debug", parse_mode="Markdown", reply_markup=get_keyboard())

async def stato_cmd(update, context):
    chat_id = update.effective_chat.id
    u = users.get(chat_id)
    if not u: await update.message.reply_text("Non registrato. Invia Live."); return
    feats = await asyncio.to_thread(query_all_interventions)
    vicini = 0
    for f in feats:
        g=f.get("geometry",{}); lat=g.get("y"); lon=g.get("x")
        if lat and haversine(u["lat"], u["lon"], lat, lon) <= u["radius"]: vicini+=1
    await update.message.reply_text(f"📊 Debug V3\nTotale Piemonte 6h: {len(feats)}\nEntro tuo raggio {int(u['radius']/1000)}km: {vicini}\nVisti: {len(u['seen'])}\nPos: {u['lat']:.5f},{u['lon']:.5f}", parse_mode="Markdown")

async def test_cmd(update, context):
    chat_id = update.effective_chat.id
    u = users.get(chat_id)
    if not u: await update.message.reply_text("Prima posizione!"); return
    maps_url=f"https://www.google.com/maps/search/?api=1&query={u['lat']+0.005},{u['lon']+0.005}"
    await context.bot.send_message(chat_id=chat_id, text=f"🧪 *TEST OK* - raggio {int(u['radius']/1000)}km funziona!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Maps", url=maps_url)]]))

async def raggio_cb(update, context):
    q=update.callback_query
    try: await q.answer()
    except: pass
    chat_id = update.effective_chat.id
    data = q.data
    print(f"CALLBACK {chat_id} -> {data}")
    if data == "raggio_test": await test_cmd(update, context); return
    if data == "raggio_vicini": await show_vicini(update, context, silent=False); return
    if data == "raggio_stop":
        if chat_id in users: del users[chat_id]; save_users()
        await q.edit_message_text("🔇 Stop."); return
    if chat_id not in users:
        await q.edit_message_text("Prima posizione Live!"); return
    try:
        km=int(data.split("_")[1]); users[chat_id]["radius"]=km*1000; save_users()
        await q.edit_message_text(f"✅ Raggio {km}km impostato! Cerco interventi...", reply_markup=get_keyboard())
        await show_vicini(update, context, silent=False)
    except Exception as e: print(f"cb err {e}")

async def post_init(app):
    global app_ref; app_ref=app; asyncio.create_task(background_loop())

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
    print(f"Avviato V3 FIX RAGGIO - {len(users)} utenti")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
