import asyncio, json, os, requests, threading, math
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
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Bot VVF LIVE PRO attivo"
def run_flask(): flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
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
def haversine(lat1, lon1, lat2, lon2):
    R=6371000; p1=math.radians(lat1); p2=math.radians(lat2); dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2; return R*2*math.asin(math.sqrt(a))
def query_arcgis(lat, lon, radius):
    params = {"f":"json","where":"1=1","geometry":f"{lon},{lat}","geometryType":"esriGeometryPoint","inSR":"4326","spatialRel":"esriSpatialRelIntersects","distance":radius,"units":"esriSRUnit_Meter","outFields":"*","returnGeometry":"true","orderByFields":"OBJECTID DESC","resultRecordCount":30}
    try: return requests.get(ARCGIS_URL, params=params, timeout=20).json().get("features",[])
    except: return []
def get_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("🏙️ 5km Città", callback_data="raggio_5"), InlineKeyboardButton("🏘️ 10km", callback_data="raggio_10")],[InlineKeyboardButton("🚗 15km", callback_data="raggio_15"), InlineKeyboardButton("🚒 30km", callback_data="raggio_30")],[InlineKeyboardButton("🗺️ 50km Provincia", callback_data="raggio_50")]])
async def check_vvf_and_send():
    global interventi_visti
    if not location_set or app_ref is None: return
    try:
        features = await asyncio.to_thread(query_arcgis, current_lat, current_lon, current_radius_m)
        if len(interventi_visti)==0 and len(features)>1:
            for f in features: interventi_visti.add(f["attributes"].get("OBJECTID"))
            features=features[:1]
        for feat in features:
            attr=feat.get("attributes",{}); oid=attr.get("OBJECTID")
            if oid in interventi_visti: continue
            interventi_visti.add(oid); tip=attr.get("TIPOLOGIA") or "Intervento VVF"; sotto=attr.get("SOTTOTIPOLOGIA") or ""; comune=attr.get("COMUNE") or ""; indir=attr.get("INDIRIZZO") or attr.get("LOCALITA") or ""; data=attr.get("DATA_SEGNALAZIONE") or ""; data_str=str(data)[:16] if data else ""; lat=feat.get("geometry",{}).get("y"); lon=feat.get("geometry",{}).get("x")
            if lat is None: continue
            dist=haversine(current_lat, current_lon, lat, lon); dist_txt=f"{dist/1000:.1f}km" if dist>=1000 else f"{int(dist)}m"; maps_url=f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            msg=f"🚨 *NUOVO INTERVENTO VVF!* 🚒\n\n📋 *{tip}*"
            if sotto: msg+=f" - {sotto}"
            msg+=f"\n📍 *{comune}* {indir}"
            if data_str: msg+=f"\n🕐 {data_str}"
            msg+=f"\n📏 {dist_txt} da te (entro {int(current_radius_m/1000)}km)\n\n[📍 APRI MAPS]({maps_url})"
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Naviga con Maps", url=maps_url)]])
            await app_ref.bot.send_message(chat_id=MY_CHAT_ID, text=msg, parse_mode="Markdown", reply_markup=kb)
    except Exception as e: print(e)
async def background_loop():
    await asyncio.sleep(10)
    while True: await check_vvf_and_send(); await asyncio.sleep(90)
async def handle_loc(u,c):
    global current_lat, current_lon, location_set
    if u.effective_chat.id!=MY_CHAT_ID: return
    loc=u.message.location; current_lat=loc.latitude; current_lon=loc.longitude; location_set=True; save_location(current_lat, current_lon, current_radius_m); is_live="LIVE 🔴" if u.message.location.live_period else "fissa 📍"
    await u.message.reply_text(f"✅ Posizione {is_live} aggiornata!\n📍 {current_lat:.5f}, {current_lon:.5f}\nRaggio: {int(current_radius_m/1000)}km", reply_markup=get_keyboard()); await check_vvf_and_send()
async def start_cmd(u,c):
    if u.effective_chat.id!=MY_CHAT_ID: return
    stato="✅ LIVE attiva" if location_set else "⚠️ non impostata"; await u.message.reply_text(f"🚒 *Bot VVF Live PRO*\n\nPosizione: {stato}\nCentro: {current_lat:.5f}, {current_lon:.5f}\nRaggio: {int(current_radius_m/1000)}km\n\n📎 Condividi posizione live (8h)", parse_mode="Markdown", reply_markup=get_keyboard())
async def raggio_cb(u,c):
    global current_radius_m; q=u.callback_query; await q.answer(); km=int(q.data.split("_")[1]); current_radius_m=km*1000; save_location(current_lat, current_lon, current_radius_m); await q.edit_message_text(f"✅ Raggio impostato a {km}km\nOra ricevi entro {km}km da te.\nPos: {current_lat:.5f}, {current_lon:.5f}", reply_markup=get_keyboard()); await check_vvf_and_send()
async def post_init(app): global app_ref; app_ref=app; asyncio.create_task(background_loop())
def main():
    load_location(); threading.Thread(target=run_flask, daemon=True).start(); app=ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build(); app.add_handler(CommandHandler("start", start_cmd)); app.add_handler(CallbackQueryHandler(raggio_cb, pattern="^raggio_")); app.add_handler(MessageHandler(filters.LOCATION, handle_loc)); print(f"Avviato LIVE PRO - {current_radius_m/1000}km"); app.run_polling()
if __name__=="__main__": main()
