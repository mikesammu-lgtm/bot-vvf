
import asyncio, json, os, requests, threading
from datetime import datetime
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

TELEGRAM_TOKEN = "8731559080:AAGEeCrhmyG0JHBF2RU8CKnRhg-zwtSlhAQ"
MY_CHAT_ID = 729488977

ARCGIS_URL = "https://services3.arcgis.com/MfVi0khS4tCyLmo3/arcgis/rest/services/Interventi_VVF_Assegnati_-_Ultime_6_ore/FeatureServer/0/query"
LOCATION_FILE = "last_location.json"

current_lat, current_lon, current_radius_m = 44.7339, 7.3168, 30000
interventi_visti = set()
location_set = False
app_ref = None

# Mini web server per tenere vivo Render
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Bot VVF LIVE attivo - 30km"

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def save_location(lat, lon, radius):
    try:
        with open(LOCATION_FILE, "w") as f: json.dump({"lat": lat, "lon": lon, "radius": radius}, f)
    except: pass

def load_location():
    global current_lat, current_lon, current_radius_m, location_set
    if os.path.exists(LOCATION_FILE):
        try:
            with open(LOCATION_FILE) as f:
                d=json.load(f); current_lat=d["lat"]; current_lon=d["lon"]; current_radius_m=d.get("radius",30000); location_set=True
        except: pass

def query_arcgis(lat, lon, radius):
    params = {"f":"json","where":"1=1","geometry":f"{lon},{lat}","geometryType":"esriGeometryPoint","inSR":"4326","spatialRel":"esriSpatialRelIntersects","distance":radius,"units":"esriSRUnit_Meter","outFields":"*","returnGeometry":"true","orderByFields":"OBJECTID DESC","resultRecordCount":25}
    try: return requests.get(ARCGIS_URL, params=params, timeout=20).json().get("features",[])
    except: return []

def get_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏙️ 5km", callback_data="raggio_5"), InlineKeyboardButton("🏘️ 10km", callback_data="raggio_10")],[InlineKeyboardButton("🚗 15km", callback_data="raggio_15"), InlineKeyboardButton("🚒 30km", callback_data="raggio_30")],[InlineKeyboardButton("🗺️ 50km", callback_data="raggio_50")]])

async def check_vvf_and_send():
    global interventi_visti
    if not location_set or app_ref is None: return
    try:
        features = await asyncio.to_thread(query_arcgis, current_lat, current_lon, current_radius_m)
        if len(interventi_visti)==0 and len(features)>1:
            for f in features: interventi_visti.add(f["attributes"].get("OBJECTID"))
            features=features[:1]
        for feat in features:
            oid=feat["attributes"].get("OBJECTID")
            if oid in interventi_visti: continue
            interventi_visti.add(oid)
            a=feat["attributes"]; tip=a.get("TIPOLOGIA") or "Intervento VVF"; com=a.get("COMUNE") or ""; ind=a.get("INDIRIZZO") or a.get("LOCALITA") or ""
            lat=feat["geometry"]["y"]; lon=feat["geometry"]["x"]
            msg=f"🚒 *NUOVO VVF!*\n📋 {tip}\n📍 {com} {ind}\n📏 Entro {int(current_radius_m/1000)}km\n[📍 Maps](https://www.google.com/maps?q={lat},{lon})"
            await app_ref.bot.send_message(chat_id=MY_CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e: print(e)

async def background_loop():
    await asyncio.sleep(10)
    while True: await check_vvf_and_send(); await asyncio.sleep(90)

async def handle_loc(u,c):
    global current_lat, current_lon, location_set
    if u.effective_chat.id!=MY_CHAT_ID: return
    loc=u.message.location; current_lat=loc.latitude; current_lon=loc.longitude; location_set=True
    save_location(current_lat, current_lon, current_radius_m)
    is_live="LIVE 🔴" if loc.live_period else "fissa 📍"
    await u.message.reply_text(f"✅ Pos {is_live} ok! {current_lat:.5f},{current_lon:.5f} Raggio {int(current_radius_m/1000)}km", reply_markup=get_keyboard())
    await check_vvf_and_send()

async def start_cmd(u,c):
    if u.effective_chat.id!=MY_CHAT_ID: return
    await u.message.reply_text(f"🚒 Bot VVF Live\nRaggio {int(current_radius_m/1000)}km\nPos {current_lat:.5f},{current_lon:.5f}\n📎 Condividi live 8h", reply_markup=get_keyboard())

async def raggio_cb(u,c):
    global current_radius_m
    q=u.callback_query; await q.answer()
    km=int(q.data.split("_")[1]); current_radius_m=km*1000; save_location(current_lat, current_lon, current_radius_m)
    await q.edit_message_text(f"✅ Raggio {km}km", reply_markup=get_keyboard())

async def post_init(app): 
    global app_ref; app_ref=app; asyncio.create_task(background_loop())

def main():
    load_location()
    threading.Thread(target=run_flask, daemon=True).start()
    app=ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(raggio_cb, pattern="^raggio_"))
    app.add_handler(MessageHandler(filters.LOCATION, handle_loc))
    print(f"Avviato LIVE Render - {current_radius_m/1000}km")
    app.run_polling()

if __name__=="__main__": main()
