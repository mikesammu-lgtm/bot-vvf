
import asyncio, json, os, requests, threading, math
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

TELEGRAM_TOKEN = "8731559080:AAGEeCrhmyG0JHBF2RU8CKnRhg-zwtSlhAQ"
ARCGIS_URL = "https://services3.arcgis.com/MfVi0khS4tCyLmo3/arcgis/rest/services/Interventi_VVF_Assegnati_-_Ultime_6_ore/FeatureServer/0/query"
USERS_FILE = "users.json"

# users = {chat_id: {"lat":..., "lon":..., "radius":..., "seen": set()}}
users = {}
app_ref = None

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return f"Bot VVF MULTI attivo - {len(users)} utenti"
def run_flask(): flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def save_users():
    try:
        data = {str(k): {"lat": v["lat"], "lon": v["lon"], "radius": v["radius"]} for k,v in users.items()}
        with open(USERS_FILE, "w") as f: json.dump(data, f)
    except: pass

def load_users():
    global users
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                data = json.load(f)
                for k,v in data.items():
                    users[int(k)] = {"lat": v["lat"], "lon": v["lon"], "radius": v.get("radius",30000), "seen": set()}
        except: pass

def haversine(lat1, lon1, lat2, lon2):
    R=6371000; p1=math.radians(lat1); p2=math.radians(lat2); dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

def query_arcgis(lat, lon, radius):
    params = {"f":"json","where":"1=1","geometry":f"{lon},{lat}","geometryType":"esriGeometryPoint","inSR":"4326","spatialRel":"esriSpatialRelIntersects","distance":radius,"units":"esriSRUnit_Meter","outFields":"*","returnGeometry":"true","orderByFields":"OBJECTID DESC","resultRecordCount":20}
    try: return requests.get(ARCGIS_URL, params=params, timeout=20).json().get("features",[])
    except: return []

def get_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏙️ 5km", callback_data="raggio_5"), InlineKeyboardButton("🏘️ 10km", callback_data="raggio_10")],[InlineKeyboardButton("🚗 15km", callback_data="raggio_15"), InlineKeyboardButton("🚒 30km", callback_data="raggio_30")],[InlineKeyboardButton("🗺️ 50km", callback_data="raggio_50"), InlineKeyboardButton("🔇 Stop", callback_data="raggio_stop")]])

async def check_all_users():
    if app_ref is None: return
    for chat_id, u in list(users.items()):
        try:
            features = await asyncio.to_thread(query_arcgis, u["lat"], u["lon"], u["radius"])
            if len(u["seen"])==0 and len(features)>1:
                for f in features: u["seen"].add(f["attributes"].get("OBJECTID"))
                features=features[:1]
            for feat in features:
                attr=feat.get("attributes",{}); oid=attr.get("OBJECTID")
                if oid in u["seen"]: continue
                u["seen"].add(oid)
                tip=attr.get("TIPOLOGIA") or "Intervento VVF"; sotto=attr.get("SOTTOTIPOLOGIA") or ""; comune=attr.get("COMUNE") or ""; indir=attr.get("INDIRIZZO") or attr.get("LOCALITA") or ""; data=attr.get("DATA_SEGNALAZIONE") or ""; data_str=str(data)[:16] if data else ""
                lat=feat.get("geometry",{}).get("y"); lon=feat.get("geometry",{}).get("x")
                if lat is None: continue
                dist=haversine(u["lat"], u["lon"], lat, lon); dist_txt=f"{dist/1000:.1f}km" if dist>=1000 else f"{int(dist)}m"
                maps_url=f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                msg=f"🚨 *NUOVO INTERVENTO VVF!* 🚒\n\n📋 *{tip}*"
                if sotto: msg+=f" - {sotto}"
                msg+=f"\n📍 *{comune}* {indir}"
                if data_str: msg+=f"\n🕐 {data_str}"
                msg+=f"\n📏 {dist_txt} da te (entro {int(u['radius']/1000)}km)\n\n[📍 APRI MAPS]({maps_url})"
                kb=InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Naviga con Maps", url=maps_url)]])
                await app_ref.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown", reply_markup=kb)
        except Exception as e: print(f"check {chat_id} error {e}")

async def background_loop():
    await asyncio.sleep(10)
    while True:
        await check_all_users()
        await asyncio.sleep(90)

async def handle_loc(u,c):
    chat_id = u.effective_chat.id
    loc = u.message.location
    if chat_id not in users:
        users[chat_id] = {"lat": loc.latitude, "lon": loc.longitude, "radius": 30000, "seen": set()}
    else:
        users[chat_id]["lat"] = loc.latitude
        users[chat_id]["lon"] = loc.longitude
    save_users()
    is_live="LIVE 🔴" if u.message.location.live_period else "fissa 📍"
    await u.message.reply_text(f"✅ Posizione {is_live} salvata SOLO per te!\n📍 {loc.latitude:.5f}, {loc.longitude:.5f}\nRaggio: {int(users[chat_id]['radius']/1000)}km\n\nOra ricevi allarmi personalizzati. Puoi dare il bot anche ai tuoi amici, ognuno avrà i suoi!", reply_markup=get_keyboard())

async def start_cmd(u,c):
    chat_id = u.effective_chat.id
    if chat_id in users:
        stato=f"✅ Attiva - {users[chat_id]['lat']:.4f}, {users[chat_id]['lon']:.4f} ({int(users[chat_id]['radius']/1000)}km)"
    else:
        stato="⚠️ Non hai ancora inviato la posizione"
    await u.message.reply_text(f"🚒 *Bot VVF MULTI-UTENTE*\n\n{stato}\n\n📎 Invia posizione LIVE 8h per ricevere allarmi vicino a te.\nOgnuno che usa questo bot ha i suoi allarmi privati!", parse_mode="Markdown", reply_markup=get_keyboard())

async def raggio_cb(u,c):
    q=u.callback_query; await q.answer(); chat_id=q.message.chat.id
    if q.data=="raggio_stop":
        if chat_id in users: del users[chat_id]; save_users()
        await q.edit_message_text("🔇 Allarmi disattivati per te. Invia di nuovo la posizione per riattivare.")
        return
    if chat_id not in users:
        await q.edit_message_text("Prima invia la posizione! 📎 -> Posizione -> Live 8h")
        return
    km=int(q.data.split("_")[1]); users[chat_id]["radius"]=km*1000; save_users()
    await q.edit_message_text(f"✅ Raggio tuo impostato a {km}km", reply_markup=get_keyboard())

async def post_init(app):
    global app_ref; app_ref=app; asyncio.create_task(background_loop())

def main():
    load_users()
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    threading.Thread(target=run_flask, daemon=True).start()
    app=ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(raggio_cb, pattern="^raggio_"))
    app.add_handler(MessageHandler(filters.LOCATION, handle_loc))
    print(f"Avviato MULTI - {len(users)} utenti")
    app.run_polling()

if __name__=="__main__": main()
