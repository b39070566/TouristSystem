import dash
from dash import dcc, html, Output, Input, State, no_update, callback_context
from dash.dependencies import ALL
import requests
import json
import math
import sqlite3
import os
from datetime import datetime
import ast
import threading
from dotenv import load_dotenv


from flask import Flask, redirect
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dash.exceptions import PreventUpdate

# ----------------------------------------------------
# 🔐 設定與資料庫初始化 (SQLite & Flask-Login)
# ----------------------------------------------------

# 初始化 Flask Server 與 Dash
server = Flask(__name__)
server.secret_key = 'CHANGE_THIS_SECRET_KEY_IN_PRODUCTION'  # 用於 Session 加密

# 使用專案中的 `assets` 資料夾來載入全域 CSS（例如 assets/style.css）
app = dash.Dash(__name__, server=server, assets_folder='assets')
app.config.suppress_callback_exceptions = True  # 必須開啟，因為我們是動態切換 Layout

# 初始化 LoginManager
login_manager = LoginManager()
login_manager.init_app(server)
login_manager.login_view = '/login'

# --- SQLite 資料庫設定 ---
# 修改前
# DB_NAME = os.path.join(os.path.dirname(__file__), "users.db")

# 修改後 (強制獲取絕對路徑並處理 Windows 的斜線問題)
# --- 尋找這段並替換 ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# 修改 DB_NAME 的定義（約第 35 行）
# 請將這裡改成你電腦上的絕對路徑，且確保資料夾已手動建立
DB_NAME = r"d:\Users\master_file\PythonCode_Basic\Midterm-main\users.db"

# 建議在這裡加一行 print，啟動時你就能在終端機看到正確路徑
print(f"✅ 資料庫絕對路徑設定為: {DB_NAME}")

# 1. 移除 DB_LOCK，保留最基礎的連線與初始化
def db_connect():
    """回傳最簡單的 sqlite3 連線，不使用任何進階 thread 參數，避免衝突"""
    return sqlite3.connect(DB_NAME, timeout=20)

def init_db():
    """初始化資料庫，強制使用最穩定的模式，確保實體寫入"""
    conn = db_connect()
    c = conn.cursor()
    # 建立 users 表
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)''')
    # 建立 itineraries 表 (目前行程)
    c.execute('''CREATE TABLE IF NOT EXISTS itineraries 
                 (user_id INTEGER PRIMARY KEY, selected_json TEXT NOT NULL, budgets_json TEXT NOT NULL, details_json TEXT NOT NULL)''')
    # 建立 itinerary_history 表 (歷史紀錄)
    c.execute('''CREATE TABLE IF NOT EXISTS itinerary_history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT, 
                  selected_json TEXT NOT NULL, budgets_json TEXT, details_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
    # 在 init_db() 中，建立 itinerary_history 表後面加這段
    c.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_itinerary_history_user_title
    ON itinerary_history(user_id, title)
""")

    conn.commit()
    # 強制設定：不使用 WAL 快照，確保每次儲存都是直接寫入硬碟檔
    try:
        c.execute("PRAGMA journal_mode=DELETE")
        c.execute("PRAGMA synchronous=FULL")
    except:
        pass
    conn.close()
    print("✅ 資料庫簡單模式初始化完成")

# 2. 保留這個解析函式 (這是 UI 點擊必要的工具)
def _get_triggered_index():
    ctx = callback_context
    if not ctx.triggered:
        return None
    t_id = ctx.triggered_id
    if isinstance(t_id, dict):
        return t_id.get('index')
    return None

# 3. 簡化後的現有行程儲存/載入 (移除 DB_LOCK 與複雜邏輯)
# --- 修正後的行程儲存/載入工具 ---

def save_user_itinerary(user_id, selected, budgets, details_subset):
    """簡單版儲存：移除 updated_at 欄位，確保與簡化版 init_db 對齊"""
    conn = db_connect()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO itineraries (user_id, selected_json, budgets_json, details_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                selected_json = excluded.selected_json,
                budgets_json = excluded.budgets_json,
                details_json = excluded.details_json
        """, (
            int(user_id),
            json.dumps(selected or [], ensure_ascii=False),
            json.dumps(budgets or {}, ensure_ascii=False),
            json.dumps(details_subset or {}, ensure_ascii=False),
        ))
        conn.commit()
    finally:
        conn.close()

def load_user_itinerary(user_id):
    """簡單版讀取：直接回傳結果"""
    if not user_id: return {"selected": [], "budgets": {}, "details": {}}
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT selected_json, budgets_json, details_json FROM itineraries WHERE user_id = ?", (int(user_id),))
    row = c.fetchone()
    conn.close()
    if not row: return {"selected": [], "budgets": {}, "details": {}}
    try:
        return {"selected": json.loads(row[0]), "budgets": json.loads(row[1]), "details": json.loads(row[2])}
    except:
        return {"selected": [], "budgets": {}, "details": {}}

def add_history_itinerary(user_id, selected, budgets, details_subset, title=None):
    """簡單版歷史儲存：移除所有複雜的 PRAGMA 和重試"""
    conn = db_connect()
    c = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute(
        "INSERT INTO itinerary_history (user_id, title, selected_json, budgets_json, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            int(user_id),
            title or f"儲存於 {now_str}",
            json.dumps(selected or [], ensure_ascii=False),
            json.dumps(budgets or {}, ensure_ascii=False),
            json.dumps(details_subset or {}, ensure_ascii=False),
            now_str
        )
    )
    conn.commit()
    conn.close()
    print(f"✅ 行程已成功儲存至歷史紀錄")

def load_user_itineraries(user_id):
    """簡單版歷史列表：一次性讀取"""
    if not user_id: return []
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT id, title, selected_json, budgets_json, details_json, created_at FROM itinerary_history WHERE user_id = ? ORDER BY created_at DESC", (int(user_id),))
    rows = c.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            out.append({
                "id": r[0], "title": r[1],
                "selected": json.loads(r[2]),
                "budgets": json.loads(r[3]),
                "details": json.loads(r[4]),
                "created_at": r[5]
            })
        except: continue
    return out

# --- 多筆歷史行程表（每個使用者可儲存多筆） -----------------
def add_history_itinerary(user_id, selected, budgets, details_subset, title=None):
    """
    簡單版行程儲存：
    移除所有 DB_LOCK 與複雜的 PRAGMA Checkpoint 邏輯，
    確保資料直接寫入實體硬碟。
    """
    selected = selected or []
    budgets = budgets or {}
    details_subset = details_subset or {}

    conn = db_connect() # 使用我們簡化過的連線函式
    c = conn.cursor()
    
    try:
        # 直接執行插入動作
        c.execute(
            "INSERT INTO itinerary_history (user_id, title, selected_json, budgets_json, details_json) VALUES (?, ?, ?, ?, ?)",
            (
                int(user_id),
                title or f"儲存於 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                json.dumps(selected, ensure_ascii=False),
                json.dumps(budgets, ensure_ascii=False),
                json.dumps(details_subset, ensure_ascii=False),
            )
        )
        conn.commit() # 實體提交至硬碟
        
        # 簡化後的 Debug 訊息，僅確認是否成功寫入
        print(f"[DEBUG] add_history_itinerary: 成功寫入 ID 為 {user_id} 的行程")
        
    except Exception as e:
        print(f"[ERROR] add_history_itinerary 儲存失敗: {e}")
    finally:
        conn.close() # 務必關閉連線，這會釋放檔案鎖


def load_user_itineraries(user_id):
    """簡單版讀取：直接查詢，不使用鎖"""
    if not user_id:
        return []
    conn = db_connect()
    c = conn.cursor()
    out = []
    try:
        # 移除原本的 with DB_LOCK:
        c.execute("SELECT id, title, selected_json, budgets_json, details_json, created_at FROM itinerary_history WHERE user_id = ? ORDER BY created_at DESC", (int(user_id),))
        rows = c.fetchall()
        for r in rows:
            try:
                out.append({
                    "id": r[0],
                    "title": r[1],
                    "selected": json.loads(r[2]),
                    "budgets": json.loads(r[3]),
                    "details": json.loads(r[4]),
                    "created_at": r[5]
                })
            except:
                continue
    except Exception as e:
        print(f"[ERROR] load_user_itineraries 查詢失敗: {e}")
    finally:
        conn.close()
    return out


def delete_itinerary_history(entry_id, user_id):
    """簡單版刪除：直接提交變更"""
    conn = db_connect()
    c = conn.cursor()
    try:
        # 移除原本的 with DB_LOCK:
        c.execute("DELETE FROM itinerary_history WHERE id = ? AND user_id = ?", (int(entry_id), int(user_id)))
        conn.commit()
    finally:
        conn.close()


def get_history_entry(entry_id, user_id):
    """簡單版單筆讀取"""
    conn = db_connect()
    c = conn.cursor()
    try:
        # 移除原本的 with DB_LOCK:
        c.execute("SELECT id, title, selected_json, budgets_json, details_json, created_at FROM itinerary_history WHERE id = ? AND user_id = ?", (int(entry_id), int(user_id)))
        row = c.fetchone()
        if row:
            return {
                "id": row[0],
                "title": row[1],
                "selected": json.loads(row[2]),
                "budgets": json.loads(row[3]),
                "details": json.loads(row[4]),
                "created_at": row[5]
            }
    finally:
        conn.close()
    return None

    
    # 解析 JSON... (保留原本邏輯)
    try:
        sel = json.loads(row[2])
        budgets = json.loads(row[3])
        details = json.loads(row[4])
    except:
        sel, budgets, details = [], {}, {}
        
    return {"id": row[0], "title": row[1], "selected": sel, "budgets": budgets, "details": details, "created_at": row[5]}

def rename_itinerary_history(entry_id, user_id, new_title: str):
    """只改歷史紀錄 title；同一 user_id 下不允許同名"""
    new_title = (new_title or "").strip()
    if not new_title:
        return {"ok": False, "msg": "名稱不可為空白"}

    conn = db_connect()
    c = conn.cursor()
    try:
        # 先檢查是否同名（避免觸發 UNIQUE INDEX 的例外，也能給更友善訊息）
        c.execute("""
            SELECT 1 FROM itinerary_history
            WHERE user_id = ? AND title = ? AND id <> ?
            LIMIT 1
        """, (int(user_id), new_title, int(entry_id)))
        if c.fetchone():
            return {"ok": False, "msg": "同名歷史紀錄已存在，請改用不同名稱"}

        c.execute("""
            UPDATE itinerary_history
            SET title = ?
            WHERE id = ? AND user_id = ?
        """, (new_title, int(entry_id), int(user_id)))
        conn.commit()

        if c.rowcount == 0:
            return {"ok": False, "msg": "找不到該筆紀錄，或無權限修改"}
        return {"ok": True, "msg": "已更新名稱"}
    except Exception as e:
        # 若 DB 層 UNIQUE INDEX 仍被撞到，這裡也會擋
        return {"ok": False, "msg": f"更新失敗：{e}"}
    finally:
        conn.close()



# --- 使用者模型 (配合 Flask-Login) ---
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
# --- 修正後的 load_user ---
@login_manager.user_loader
def load_user(user_id):
    conn = db_connect()
    c = conn.cursor()
    # 移除 with DB_LOCK:
    c.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    if res:
        return User(id=res[0], username=res[1])
    return None

# ----------------------------------------------------
# 🔧 原本 easier.py 的設定與常數
# ----------------------------------------------------

# ⚠️ API key 優先從環境變數或 .env 讀取，避免硬編碼到程式中
API_KEY = os.environ.get('API_KEY')
if not API_KEY:
    try:
        from dotenv import load_dotenv
        load_dotenv()
        API_KEY = os.environ.get('API_KEY')
    except Exception:
        pass

# Fallback（僅在你沒有提供環境變數或 .env 時使用；建議移除或替換為空字串）
if not API_KEY:
    API_KEY = "your_google_maps_api_key_here"

PAGE_SIZE = 10

CATEGORY_TYPE_MAP = {
    "food": ["restaurant", "cafe", "bar", "bakery"],
    "fun": [
        "amusement_park", "aquarium", "art_gallery", "bowling_alley", "casino",
        "museum", "night_club", "clothing_store", "department_store",
        "tourist_attraction", "zoo", "shopping_mall", "shoe_store",
    ],
}

STYLES = {
    "container": {
        "maxWidth": "1200px", "margin": "20px auto",
        "fontFamily": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", "fontSize": 16,
    },
     "input_group": {
        "display": "flex", "flexWrap": "wrap", "alignItems": "center", "gap": "6px", "marginBottom": "10px",
        "backgroundColor": "#F0EBE0", "borderRadius": "999px", "padding": "12px 16px", "border": "1px solid #E8DDD4",
        "boxShadow": "0 4px 12px rgba(0,0,0,0.08)", "width": "fit-content"
    },
    "input_text": {"fontSize": 16, "width": "320px", "padding": "6px 8px", "borderRadius": "999px", "border": "1px solid #ddd"},
    "input_budget": {"fontSize": 16, "width": "180px", "padding": "6px 8px", "borderRadius": "999px", "border": "1px solid #ddd"},
    "btn_primary": {
        "fontSize": 16, "padding": "8px 20px", "backgroundColor": "#56602D",
        "color": "white", "border": "none", "borderRadius": "999px", "cursor": "pointer",
    },
    "card_container": {
        "border": "1px solid #ddd", "borderRadius": "4px", "padding": "10px",
        "maxHeight": "450px", "overflowY": "auto", "backgroundColor": "#fafafa",
    },
    "panel_round": {
        "backgroundColor": "#fff", "border": "1px solid #eee",
        "borderRadius": "24px", "padding": "16px",
        "boxShadow": "0 8px 24px rgba(0,0,0,0.08)", "minHeight": "75px",
    },
    # --- 修正後的 Modal 樣式，解決閃現問題 ---
    "modal_overlay": {
        "position": "fixed", "top": 0, "left": 0, "width": "100vw", "height": "100vh",
        "backgroundColor": "rgba(0,0,0,0.5)", "zIndex": 2000, "display": "none"
    },
    "modal_content": {
        "position": "fixed", "top": "50%", "left": "50%", "transform": "translate(-50%, -50%)",
        "backgroundColor": "white", "border": "1px solid #ccc", "borderRadius": "10px",
        "padding": "25px", "boxShadow": "0 4px 20px rgba(0,0,0,0.3)",
        "zIndex": 2001, "width": "450px", "maxHeight": "80vh", "overflowY": "auto",
        "display": "none"
    },
    # --- 補回登入/註冊所需的樣式，解決 KeyError ---
    "auth_container": {
        "width": "350px", "margin": "100px auto", "padding": "40px",
        "border": "1px solid #ddd", "borderRadius": "12px", "textAlign": "center",
        "boxShadow": "0 6px 15px rgba(0,0,0,0.1)", "backgroundColor": "#fff"
    },
    "auth_input": {
        "width": "100%", "padding": "12px", "marginBottom": "20px",
        "boxSizing": "border-box", "borderRadius": "6px", "border": "1px solid #ccc",
        "fontSize": "16px"
    }
}
# ----------------------------------------------------
# 🛠️ 原本 easier.py 的工具函式
# ----------------------------------------------------

def get_latlng(address, apikey):
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": apikey},
        ).json()
        if not resp.get("results"):
            return None, None
        loc = resp["results"][0]["geometry"]["location"]
        return loc["lat"], loc["lng"]
    except Exception:
        return None, None

def calculate_distance(lat1, lng1, lat2, lng2):
    if None in [lat1, lng1, lat2, lng2]:
        return float("inf")
    R = 6371
    lat1, lng1, lat2, lng2 = map(math.radians, [float(lat1), float(lng1), float(lat2), float(lng2)])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def normalize_place_data(place, user_lat, user_lng):
    raw_pl = place.get("price_level")
    try:
        place["price_level_int"] = int(raw_pl) if raw_pl is not None else None
    except:
        place["price_level_int"] = None

    lat = place.get("geometry", {}).get("location", {}).get("lat")
    lng = place.get("geometry", {}).get("location", {}).get("lng")
    place["distance_km"] = calculate_distance(user_lat, user_lng, lat, lng)

    photos = place.get("photos")
    place["photo_reference"] = photos[0].get("photo_reference") if (photos and len(photos) > 0) else None

    place_types = place.get("types", [])
    primary_type = "其他"
    for k, v in CATEGORY_TYPE_MAP.items():
        if any(t in place_types for t in v):
            primary_type = "美食" if k == "food" else "娛樂"
            break
    place["primary_type"] = primary_type

    # 取得附近搜尋回傳的評論數（若有），統一欄位名稱為 reviews_count
    # 注意：Nearby Search 有時會回傳 'user_ratings_total'，也可能不存在
    place["reviews_count"] = place.get("user_ratings_total") if place.get("user_ratings_total") is not None else None

    return place

def search_places(lat, lng, apikey, types_list, radius=1000):
    all_results = []
    seen_ids = set()

    for t in types_list:
        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                params={"location": f"{lat},{lng}", "radius": radius, "type": t, "key": apikey},
            ).json()
            results = resp.get("results", [])
            for r in results:
                pid = r.get("place_id")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    normalized_r = normalize_place_data(r, lat, lng)
                    all_results.append(normalized_r)
        except Exception as e:
            print(f"API Error: {e}")
            continue

    return all_results

def calculate_popularity_score(places_list, apikey=None):
    """
    使用評論數（reviews_count 或 user_ratings_total）作為熱門程度分數。
    若 nearby-search 沒有提供 reviews_count，會嘗試用 place details 取得 `user_ratings_total`（需要 apikey）。

    回傳值會將每個 place 加上 `popularity_score`（整數，評論數；若無資料則 0），並依此排序（降冪）。
    """
    if not places_list:
        return []

    for place in places_list:
        # 優先使用已存在的 reviews_count
        rc = place.get("reviews_count")
        if rc is None and apikey:
            # 若沒有，嘗試用 details API 取得 user_ratings_total
            try:
                details, _ = fetch_place_details(place.get("place_id"))
                rc = details.get("user_ratings_total") if isinstance(details, dict) else None
            except Exception:
                rc = None

        place["popularity_score"] = int(rc) if (rc is not None) else 0

    return sorted(places_list, key=lambda x: x.get("popularity_score", 0), reverse=True)

def fetch_place_details(place_id):
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id, "key": API_KEY, "language": "zh-TW",
                "fields": "name,rating,formatted_address,formatted_phone_number,website,review,price_level,user_ratings_total,opening_hours",
            },
        ).json()
        result = resp.get("result", {})
        return result, result.get("reviews", [])[:3]
    except:
        return {}, []

# ----------------------------------------------------
# 📱 Layouts (登入、註冊、主程式)
# ----------------------------------------------------

# 1. 登入介面 Layout
login_layout = html.Div([
    html.H2("使用者登入", style={"marginBottom": "20px"}),
    dcc.Input(id="login-user", type="text", placeholder="帳號", style=STYLES["auth_input"]),
    dcc.Input(id="login-pwd", type="password", placeholder="密碼", style=STYLES["auth_input"]),
    html.Button("登入", id="login-btn", style={**STYLES["btn_primary"], "width": "100%", "marginBottom": "10px"}),
    html.Div(id="login-output", style={"color": "red", "marginBottom": "10px"}),
    html.Div([
        "還沒有帳號？ ",
        dcc.Link("點此註冊", href="/register", style={"color": "#1976D2", "fontWeight": "bold"})
    ])
], style=STYLES["auth_container"])

# 2. 註冊介面 Layout
register_layout = html.Div([
    html.H2("新用戶註冊", style={"marginBottom": "20px"}),
    dcc.Input(id="reg-user", type="text", placeholder="設定帳號", style=STYLES["auth_input"]),
    dcc.Input(id="reg-pwd", type="password", placeholder="設定密碼", style=STYLES["auth_input"]),
    html.Button("註冊", id="reg-btn", style={**STYLES["btn_primary"], "width": "100%", "marginBottom": "10px"}),
    html.Div(id="reg-output", style={"color": "red", "marginBottom": "10px"}),
    html.Div([
        "已有帳號？ ",
        dcc.Link("返回登入", href="/login", style={"color": "#1976D2", "fontWeight": "bold"})
    ])
], style=STYLES["auth_container"])

# 3. 主程式 Layout
def get_app_layout(username):
    # ✅ 登入後載入該使用者上次儲存的行程
    stored = load_user_itinerary(current_user.id) if current_user.is_authenticated else {"selected": [], "budgets": {}, "details": {}}
    stored_selected = stored.get("selected", [])
    stored_budgets  = stored.get("budgets", {})
    stored_details  = stored.get("details", {})

    return html.Div([
        html.Div([
        # Header: 顯示使用者與登出按鈕
         html.Div([
                html.Span(f"👋 Hi, {username}", style={"fontWeight": "bold", "marginRight": "15px"}),
                dcc.Link(html.Button("登出", style={"fontSize": "14px", "padding": "4px 10px", "cursor": "pointer", "backgroundColor": "transparent", "border": "1px solid #3d1b05", "color": "#3d1b05"}), href="/logout"),
            ], style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "10px", "marginLeft": "auto", "width": "fit-content"}),

            dcc.Loading(
                id="loading-search", type="circle", fullscreen=True, color="#0B16EA",
                style={"transform": "scale(2)"}, children=dcc.Store(id="loading-trigger-store")
            ),

            html.Div([
                html.Div([
                    html.H1("附近行程智慧推薦", className="section-title", style={"marginBottom": "5px"}),
                    html.P("輸入出發地與預算，系統將為您推薦最佳行程。", style={"marginTop": "0px", "color": "#555"}),
                    html.Div([
                        html.Div([
                            dcc.Input(
                                id="address", type="text", placeholder="輸入出發地址，例如：台北車站", style=STYLES["input_text"]
                            ),
                            html.Span("*", style={"color": "red", "fontWeight": "bold", "marginLeft": "4px", "fontSize": "16px"}),
                        ], style={"display": "flex", "alignItems": "center", "gap": "2px"}),
                        html.Div([
                            dcc.Input(
                                id="budget", type="number", placeholder="單點預算限制", value=None, style={"width": "120px", "padding": "6px", "borderRadius": "999px", "border": "1px solid #ddd"}
                            ),
                            html.Span("*", style={"color": "red", "fontWeight": "bold", "marginLeft": "4px", "fontSize": "16px"}),
                        ], style={"display": "flex", "alignItems": "center", "gap": "2px"}),
                        html.Div([
                            dcc.Input(
                                id="total-trip-budget", type="number", placeholder="預算上限 (TWD)", value=None, style=STYLES["input_budget"]
                            ),
                            html.Span("*", style={"color": "red", "fontWeight": "bold", "marginLeft": "4px", "fontSize": "16px"}),
                        ], style={"display": "flex", "alignItems": "center", "gap": "2px"}),
                        dcc.Dropdown(
                            id="category",
                            options=[{"label": "美食", "value": "food"}, {"label": "娛樂", "value": "fun"}],
                            value=["food", "fun"],
                            multi=True, clearable=False,
                            style={"width": "260px", "verticalAlign": "middle"}
                        ),
                        html.Button("查詢", id="search-btn", n_clicks=0, style=STYLES["btn_primary"]),
                    ], style=STYLES["input_group"]),


        html.Div(id="budget-warning", style={"marginTop": "5px", "marginBottom": "15px", "fontSize": 16}),

# 進度條：顯示預算使用情況
            html.Div([
                html.Div(id="budget-progress-bar", style={
                    "width": "0%",
                    "height": "100%",
                    "backgroundColor": "#458a4b",
                    "borderRadius": "999px",
                    "transition": "width 0.3s ease"
                })
            ], style={
               "width": "100%",
               "height": "14px",
               "backgroundColor": "#c0d5bc",
               "borderRadius": "999px",
               "overflow": "hidden",
               "marginBottom": "15px"
            }),
        ], style={"backgroundColor": "rgba(255,255,255,0.85)", "padding": "16px", "borderRadius": "12px", "boxShadow": "0 6px 16px rgba(0,0,0,0.12)", "marginBottom": "20px"}),
    ], style={"display": "flex", "flexDirection": "column"}),

            html.Div([
                html.Div([
                    html.Div([
                        html.H3("推薦地點", style={"marginBottom": "10px"}),
                    html.Div(
                        id="result-container",
                        children=html.Div("無搜尋結果", style={"color": "#999", "textAlign": "center", "padding": "40px"}),
                        style=STYLES["card_container"]
                    ),
                    html.Div([
                        html.Button("上一頁", id="prev-page", n_clicks=0, style={"marginRight": "10px", "backgroundColor": "#56602D", "color": "white", "border": "none", "borderRadius": "999px", "padding": "6px 16px", "cursor": "pointer"}),
                        html.Span(id="page-info", style={"marginRight": "10px"}),
                        html.Button("下一頁", id="next-page", n_clicks=0, style={"backgroundColor": "#56602D", "color": "white", "border": "none", "borderRadius": "999px", "padding": "6px 16px", "cursor": "pointer"}),
                    ], style={"marginTop": "10px", "display": "flex", "justifyContent": "center", "alignItems": "center"}),
                ], style={**STYLES["panel_round"], "flex": "1", "marginRight": "20px"}),

            html.Div([
                    html.Div([
                        html.H3("已選行程", style={"marginBottom": "10px", "display": "inline-block", "marginRight": "10px"}),
                        html.Button("儲存行程並查看歷史", id="save-itinerary-btn", n_clicks=0, style={"fontSize": 13, "padding": "6px 16px", "backgroundColor": "#56602D", "color": "white", "border": "none", "borderRadius": "999px", "cursor": "pointer"}),
                    ], style={"display": "flex", "alignItems": "center", "justifyContent": "space-between"}),
                    html.Div(
                        id="selected-itinerary",
                        style={**STYLES["card_container"], "backgroundColor": "#fff", "minHeight": "50px"}
                    ),
                ], style={**STYLES["panel_round"], "flex": "1"}),
            ], style={"display": "flex", "flexDirection": "row", "marginBottom": "20px"}),
            ], style={"display": "flex", "flexDirection": "column"}),

                 html.Div([
                html.Div([
                    html.H3("預算分析", style={"marginBottom": "10px"}),
                    dcc.Graph(id="budget-pie-chart", style={"width": "100%", "height": "300px"}, config={"displayModeBar": False}),
                ], style={**STYLES["panel_round"], "marginRight": "20px", "overflowY": "hidden", "flex": "1", "minWidth": "0"}),

                html.Div([
                    html.H3("類別分析", style={"marginBottom": "10px"}),
                    dcc.Graph(id="category-pie-chart", style={"width": "100%", "height": "300px"}, config={"displayModeBar": False}),
                ], style={**STYLES["panel_round"], "overflowY": "hidden", "flex": "1", "minWidth": "0"}),
            ], style={"display": "flex", "flexDirection": "row", "marginBottom": "20px"}),

        # ✅ 只改初始值：載入上次選取
        dcc.Checklist(id="place-selector", options=[], value=stored_selected, style={"display": "none"}),

        # ✅ 只改初始值：載入上次 details（讓右側/圖表能顯示名稱等）
        dcc.Store(id="all-place-details", data=stored_details),

        dcc.Store(id="all-options", data=[]),
        dcc.Store(id="page", data=0),
        dcc.Store(id="detail-cache", data={}),
        dcc.Store(id="modal-trigger-state", data={"open": False, "pid": None}),

        # ✅ 只改初始值：載入上次手動預算
        dcc.Store(id="manual-budget-store", data=stored_budgets),

        # ✅ 新增：不影響 UI 的 dummy store，用來觸發存檔 callback
        dcc.Store(id="itinerary-persist-dummy", data=None),

        html.Div(id='detail-backdrop', n_clicks=0, style=STYLES["modal_overlay"]),
        html.Div(id='detail-modal', children="載入中...", style=STYLES["modal_content"]),

    ], style={"margin": "0 auto", "display": "flex", "flexDirection": "column", "width": "fit-content"}),

    ], style=STYLES["container"])

# --- 根 Layout：負責控制所有頁面切換 ---
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='page-content')
])

# ----------------------------------------------------
# 📡 Callbacks: Auth & Routing (認證與路由)
# ----------------------------------------------------

@app.callback(
    Output('page-content', 'children'),
    Input('url', 'pathname')
)
def display_page(pathname):
    if pathname == '/login':
        return login_layout
    elif pathname == '/register':
        return register_layout
    elif pathname == '/logout':
        logout_user()
        return login_layout
    else:
        if current_user.is_authenticated:
            if pathname == '/history':
                # 建立歷史行程頁面
                histories = load_user_itineraries(current_user.id)
                cards = []
                for h in histories:
                    # 顯示簡短的行程資訊（標題、建立時間、幾個地點名稱）
                    names = []
                    for pid in h.get('selected', [])[:6]:
                        d = h.get('details', {}).get(pid, {})
                        names.append(d.get('name', pid))

                    card_children = [
                        html.Div(h.get('title', ''), style={"fontWeight": "bold", "marginBottom": "6px"}),
                        html.Div(h.get('created_at', ''), style={"color": "#777", "fontSize": 12, "marginBottom": "6px"}),
                        html.Div(', '.join(names), style={"color": "#555", "fontSize": 13, "marginBottom": "8px", "overflow": "hidden", "textOverflow": "ellipsis"}),
                        html.Div([html.Button("查看",id={"type": "view-history", "index": h.get('id')},n_clicks=0,style={"padding": "6px 10px","borderRadius": "8px","border": "1px solid #3F5D3A","backgroundColor": "transparent","color": "#3F5D3A","cursor": "pointer"}),
                                  html.Button("載入",id={"type": "load-history", "index": h.get('id')},n_clicks=0,style={"padding": "6px 10px","borderRadius": "8px","backgroundColor": "#3F5D3A","color": "#FFFFFF","border": "none","cursor": "pointer"}),
                                  html.Button("刪除",id={"type": "delete-history", "index": h.get('id')},n_clicks=0,style={"padding": "6px 10px","borderRadius": "8px","backgroundColor": "#8B2C2C","color": "#FFFFFF","border": "none","cursor": "pointer"}),
                                  html.Button("改名",id={"type": "rename-history", "index": h.get('id')},n_clicks=0,style={"padding": "6px 10px","borderRadius": "8px","border": "1px solid #6B7C6C","backgroundColor": "transparent","color": "#2F3A2F","cursor": "pointer"})],
                                style={"display": "flex","gap": "10px",          # ✅ 等距關鍵在這"flexWrap": "wrap","marginTop": "8px"
                               })
                               ]

                    cards.append(html.Div(card_children, style={"width": "23%", "border": "1px solid #eee", "borderRadius": "6px", "padding": "10px", "boxSizing": "border-box", "marginBottom": "12px"}))

                grid = html.Div(cards, style={"display": "flex", "flexWrap": "wrap", "gap": "1%"})

                return html.Div([
                    html.Div([
                        html.Div([
                            dcc.Link(html.Button("回到主頁", style={"padding": "6px 10px", "marginRight": "8px"}), href='/'),
                            html.Button("新增新的行程", id='new-itinerary-btn', n_clicks=0, style={"padding": "6px 10px"}),
                        ], style={"textAlign": "right"})
                    ], style={"marginBottom": "10px"}),
                     html.Div(
                        html.H2("我的歷史行程", style={"margin": "0"}),
                        style={"marginBottom": "12px", "backgroundColor": "rgba(255,255,255,0.85)", "padding": "12px 16px", "borderRadius": "10px", "boxShadow": "0 6px 16px rgba(0,0,0,0.12)"}
                    ),
                    grid,
                    # 詳細 modal（會由 callback 控制顯示/內容）
                    # 修改後的版本：確保有空字串作為 children 佔位符
                    html.Div(id='history-detail-backdrop', n_clicks=0, style={**STYLES.get("modal_overlay", {}), "display": "none"}),
                    html.Div(id='history-detail-modal', children="", style={**STYLES.get("modal_content", {}), "display": "none"}),
                    # 放在 /history 頁面 layout（return html.Div([...])）的末尾、跟 detail modal 同層
                    html.Div(id='rename-backdrop', n_clicks=0, style={**STYLES.get("modal_overlay", {}), "display": "none"}),
                    html.Div(id='rename-modal',children="",style={**STYLES.get("modal_content", {}), "display": "none"}),
                    dcc.Store(id="rename-target", data={"id": None}),
                ], style=STYLES["container"])
            return get_app_layout(current_user.username)
        else:
            return login_layout

@app.callback(
    Output('url', 'pathname', allow_duplicate=True),
    Output('login-output', 'children'),
    Input('login-btn', 'n_clicks'),
    State('login-user', 'value'),
    State('login-pwd', 'value'),
    prevent_initial_call=True
)
# --- 修改前 ---
# with DB_LOCK:
#     c.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
#     user_data = c.fetchone()

# --- 修改後 (簡單版) ---
def login_callback(n_clicks, username, password):
    if not username or not password:
        return no_update, "請輸入帳號密碼"

    conn = db_connect()
    c = conn.cursor()
    # 直接執行，不使用 DB_LOCK
    c.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
    user_data = c.fetchone()
    conn.close()

    if user_data and check_password_hash(user_data[2], password):
        user = User(id=user_data[0], username=user_data[1])
        login_user(user)
        return '/', ""
    else:
        return no_update, "帳號或密碼錯誤"

@app.callback(
    Output('url', 'pathname', allow_duplicate=True),
    Output('reg-output', 'children'),
    Input('reg-btn', 'n_clicks'),
    State('reg-user', 'value'),
    State('reg-pwd', 'value'),
    prevent_initial_call=True
)
def register_callback(n_clicks, username, password):
    if not username or not password:
        return no_update, "請輸入完整資訊"

    conn = db_connect()
    c = conn.cursor()
    # 移除 with DB_LOCK:
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    if c.fetchone():
        conn.close()
        return no_update, "帳號已存在"

    hashed_pw = generate_password_hash(password)
    c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pw))
    conn.commit()
    conn.close()

    return '/login', ""

# ----------------------------------------------------
# ✅ 新增：已選行程自動儲存（不影響任何原 UI/邏輯）
# ----------------------------------------------------

# @app.callback(
#     Output("itinerary-persist-dummy", "data"),
#     Input("place-selector", "value"),
#     Input("manual-budget-store", "data"),
#     State("all-place-details", "data"),
#     prevent_initial_call=True,
# )
# def persist_itinerary(selected, budgets, all_details):
#     if not current_user.is_authenticated:
#         return no_update

#     selected = selected or []
#     budgets = budgets or {}
#     all_details = all_details or {}

#     # 只存「已選」的 details，避免 DB 爆大
#     details_subset = {pid: all_details.get(pid, {}) for pid in selected if pid in all_details}

#     try:
#         save_user_itinerary(current_user.id, selected, budgets, details_subset)
#     except Exception as e:
#         print(f"[Persist] save error: {e}")
#         return {"ok": False, "error": str(e), "ts": datetime.now().isoformat()}

#     return {"ok": True, "ts": datetime.now().isoformat()}

# ----------------------------------------------------
# 📡 Callbacks: easier.py Original Logic (完全保留)
# ----------------------------------------------------

@app.callback(
    Output("all-options", "data"),
    Output("all-place-details", "data"),
    Output("place-selector", "options"),
    Output("page", "data"),
    Output("loading-trigger-store", "data"),
    Input("address", "n_submit"),
    Input("budget", "n_submit"),
    Input("search-btn", "n_clicks"),
    State("address", "value"),
    State("budget", "value"),
    State("category", "value"),
    State("all-place-details", "data"),
    prevent_initial_call=False,
)
def search_and_build_options(submit_addr, submit_budget, n_clicks, address, budget, category, old_details):
    if not address or not budget:
        return no_update, no_update, no_update, no_update, no_update

    lat, lng = get_latlng(address, API_KEY)
    if not lat:
        return [], old_details or {}, [], 0, "done"

    types_list = []
    current_category = category if category else ["food", "fun"]
    for c in current_category:
        types_list.extend(CATEGORY_TYPE_MAP.get(c, []))

    nearby = search_places(lat, lng, API_KEY, list(set(types_list)))

    if not nearby:
        return [], old_details or {}, [], 0, "done"

    # 以評論數排序作為「熱門程度」（若 nearby 未提供則會嘗試用 details API 取得）
    nearby_scored = calculate_popularity_score(nearby, apikey=API_KEY)
    max_pl = 1 if budget <= 200 else 2 if budget <= 400 else 3 if budget <= 1400 else 4

    new_details = old_details.copy() if old_details else {}
    options = []

    for p in nearby_scored:
        new_details[p["place_id"]] = p
        pl = p["price_level_int"]
        if pl is None or pl <= max_pl:
            options.append({"label": p.get("name", "未知"), "value": p["place_id"]})

    return options, new_details, options, 0, "done"


# 儲存當前已選行程並導向歷史頁面
@app.callback(
    Output('url', 'pathname', allow_duplicate=True),
    Input('save-itinerary-btn', 'n_clicks'),
    State('place-selector', 'value'),
    State('all-place-details', 'data'),
    State('manual-budget-store', 'data'),
    prevent_initial_call=True,
)
def save_itinerary_and_go(n_clicks, selected, all_details, budgets):
    if not n_clicks:
        return no_update
    if not current_user.is_authenticated:
        return '/login'
    # 儲存為歷史紀錄
    print(f"[DEBUG] save_itinerary_and_go: user={getattr(current_user, 'id', None)}, selected_len={len(selected or [])}")
    try:
        add_history_itinerary(current_user.id, selected or [], budgets or {}, all_details or {}, title=None)
    except Exception as e:
        print(f"[ERROR] save_itinerary_and_go: {e}")
    return '/history'


# 刪除歷史行程（pattern-matching）
@app.callback(
    Output('url', 'pathname', allow_duplicate=True),
    Input({'type': 'delete-history', 'index': ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def handle_delete_history(n_clicks_list):
    # 檢查是否有按鈕被點擊
    if not any(n_clicks_list):
        return no_update
        
    # 替換掉原本報錯的 _parse_triggered_id 邏輯
    entry_id = _get_triggered_index() 
    if entry_id is None or not current_user.is_authenticated:
        return no_update

    delete_itinerary_history(entry_id, current_user.id)
    return '/history'


# 顯示歷史行程細節（modal）
@app.callback(
    [Output('history-detail-modal', 'style'),        # 必須對應 Layout 的 ID
     Output('history-detail-backdrop', 'style'),     # 必須對應 Layout 的 ID
     Output('history-detail-modal', 'children')],    # 必須對應 Layout 的 ID
    [Input({'type': 'view-history', 'index': ALL}, 'n_clicks')],
    prevent_initial_call=True,
)
def show_history_detail(n_clicks_list):
    # 診斷點 1：檢查是否真的有點擊觸發
    if not any(n_clicks for n_clicks in n_clicks_list if n_clicks > 0):
        print(">>> [DEBUG] 回調觸發，但無點擊次數，跳過更新") #
        return no_update, no_update, no_update

    entry_id = _get_triggered_index() #
    target = get_history_entry(entry_id, current_user.id) #
    
    if not target:
        print(f">>> [DEBUG] 找不到 ID={entry_id} 的行程") #
        return no_update, no_update, "找不到行程資料"

    # 生成詳細清單內容
    sel = target.get('selected', []) #
    budgets = target.get('budgets', {}) #
    details = target.get('details', {}) #
    
    items = []
    for i, pid in enumerate(sel):
        p = details.get(pid, {})
        cost = budgets.get(pid, 0)
        items.append(html.Div([
            html.Div(f"{i+1}. {p.get('name', pid)}", style={"fontWeight": "bold"}),
            html.Small(f"預算: {cost} | 熱門度: {p.get('popularity_score', 0)}", style={"color": "#666"})
        ], style={"padding": "10px", "borderBottom": "1px solid #eee"}))

    content = html.Div([
        html.H3(target.get('title', '行程詳情')),
        html.Div(items, style={"maxHeight": "300px", "overflowY": "auto"}),
        html.Hr(),
        html.Button("關閉", id={'type': 'close-history-detail', 'index': entry_id}, 
                    style={**STYLES["btn_primary"], "backgroundColor": "#555", "width": "100%"})
    ])

    # 診斷點 2：強制回傳 block，且 zIndex 必須最高
    print(f">>> [DEBUG] 成功推送到畫面，ID={entry_id}") #
    return {**STYLES["modal_content"], "display": "block", "zIndex": 9999}, \
           {**STYLES["modal_overlay"], "display": "block", "zIndex": 9998}, \
           content

# 關閉 Modal (修正後的單一邏輯) 
# 確保這是你程式碼中「唯一」一個處理關閉 Modal 的 Callback
@app.callback(
    [Output('history-detail-modal', 'style', allow_duplicate=True),
     Output('history-detail-backdrop', 'style', allow_duplicate=True)],
    [Input('history-detail-backdrop', 'n_clicks'),
     Input({'type': 'close-history-detail', 'index': ALL}, 'n_clicks')],
    prevent_initial_call=True,
)
def clean_close_modal(bg_clicks, btn_clicks):
    ctx = callback_context
    if not ctx.triggered:
        return no_update, no_update

    trig = ctx.triggered[0]["prop_id"]

    # 只有「真的點擊」才關
    if ("history-detail-backdrop" in trig and (bg_clicks or 0) > 0) or \
       ("close-history-detail" in trig and any((c or 0) > 0 for c in (btn_clicks or []))):
        return ({**STYLES["modal_content"], "display": "none"},
                {**STYLES["modal_overlay"], "display": "none"})

    return no_update, no_update

# (A) 點「改名」→ 開啟 modal、記住 entry_id
@app.callback(
    Output("rename-modal", "style"),
    Output("rename-backdrop", "style"),
    Output("rename-modal", "children"),
    Output("rename-target", "data"),
    Input({"type": "rename-history", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def open_rename_modal(n_clicks_list):
    if not any(n_clicks_list):
        return no_update, no_update, no_update, no_update

    entry_id = _get_triggered_index()
    if entry_id is None or not current_user.is_authenticated:
        return no_update, no_update, no_update, no_update

    target = get_history_entry(entry_id, current_user.id)
    if not target:
        return no_update, no_update, "找不到行程資料", no_update

    content = html.Div([
        html.H3("修改歷史行程名稱"),
        dcc.Input(id="rename-input", type="text", value=target.get("title", ""), style={"width": "100%", "padding": "8px"}),
        html.Div(id="rename-msg", style={"color": "red", "marginTop": "8px"}),
        html.Div([
            html.Button("取消", id="rename-cancel", n_clicks=0, style={"padding": "6px 10px", "marginRight": "8px"}),
            html.Button("儲存", id="rename-save", n_clicks=0, style={**STYLES["btn_primary"], "padding": "6px 10px"}),
        ], style={"marginTop": "12px", "textAlign": "right"})
    ])

    return (
        {**STYLES["modal_content"], "display": "block", "zIndex": 9999},
        {**STYLES["modal_overlay"], "display": "block", "zIndex": 9998},
        content,
        {"id": entry_id},
    )

# (B) 儲存 / 取消 / 點背景 → 關閉 modal；儲存時只改 title 且不允許同名
@app.callback(
    Output("rename-modal", "style", allow_duplicate=True),
    Output("rename-backdrop", "style", allow_duplicate=True),
    Output("rename-msg", "children"),
    Output("url", "pathname", allow_duplicate=True),  # 成功後刷新 /history 讓卡片立刻更新
    Input("rename-backdrop", "n_clicks"),
    Input("rename-cancel", "n_clicks"),
    Input("rename-save", "n_clicks"),
    State("rename-input", "value"),
    State("rename-target", "data"),
    prevent_initial_call=True,
)

def submit_rename(bg, cancel, save, new_title, target):
    ctx = callback_context
    print("RENAME submit triggered:", ctx.triggered)

    if not ctx.triggered:
        raise PreventUpdate

    # ✅ 找出「真的被點到」的那個 trigger（value > 0）
    fired = None
    for t in ctx.triggered:
        prop = t.get("prop_id", "")
        val = t.get("value", None)
        if prop.startswith("rename-backdrop") and (bg or 0) > 0:
            fired = "backdrop"
            break
        if prop.startswith("rename-cancel") and (cancel or 0) > 0:
            fired = "cancel"
            break
        if prop.startswith("rename-save") and (save or 0) > 0:
            fired = "save"
            break

    # ✅ 這就是你現在的問題：動態插入元件時會觸發 (value=0)
    if fired is None:
        raise PreventUpdate

    # 關閉（取消或點背景）
    if fired in ["backdrop", "cancel"]:
        return (
            {**STYLES["modal_content"], "display": "none"},
            {**STYLES["modal_overlay"], "display": "none"},
            "",
            no_update
        )

    # fired == "save"：儲存
    if not current_user.is_authenticated:
        return (
            {**STYLES["modal_content"], "display": "none"},
            {**STYLES["modal_overlay"], "display": "none"},
            "",
            "/login"
        )

    entry_id = (target or {}).get("id")
    if entry_id is None:
        return no_update, no_update, "找不到目標紀錄", no_update

    res = rename_itinerary_history(entry_id, current_user.id, new_title)

    if not res.get("ok"):
        # 不關閉：顯示錯誤（含同名）
        return no_update, no_update, res.get("msg", "更新失敗"), no_update

    # 成功：關閉並刷新
    return (
        {**STYLES["modal_content"], "display": "none"},
        {**STYLES["modal_overlay"], "display": "none"},
        "",
        "/history"
    )



# 載入歷史行程到主頁（保存為目前選取，然後導回主頁）
@app.callback(
    Output('url', 'pathname', allow_duplicate=True),
    Input({'type': 'load-history', 'index': ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def load_history_to_main(n_clicks_list):
    # 檢查是否有按鈕被點擊
    if not any(n_clicks_list):
        return no_update
        
    # 替換掉原本報錯的 _parse_triggered_id 邏輯
    entry_id = _get_triggered_index()
    if entry_id is None or not current_user.is_authenticated:
        return no_update

    # 直接讀取資料庫，並覆寫目前的 itineraries
    target = get_history_entry(entry_id, current_user.id)
    if not target:
        return no_update

    try:
        save_user_itinerary(current_user.id, target.get('selected', []), target.get('budgets', {}), target.get('details', {}))
    except Exception as e:
        print(f"[LoadHistory] save error: {e}")
        return no_update

    return '/'


# 新增新的行程（清空目前儲存並回主頁）
@app.callback(
    Output('url', 'pathname', allow_duplicate=True),
    Input('new-itinerary-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def new_itinerary(n_clicks):
    if not n_clicks:
        return no_update
    if not current_user.is_authenticated:
        return '/login'

    try:
        save_user_itinerary(current_user.id, [], {}, {})
    except Exception as e:
        print(f"[NewItinerary] save error: {e}")
        return no_update

    return '/'

@app.callback(
    Output("result-container", "children"),
    Output("page-info", "children"),
    Input("all-options", "data"),
    Input("page", "data"),
    Input("place-selector", "value"),
    State("all-place-details", "data"),
)
def render_page(all_options, page, selected_values, all_details):
    if not all_options:
        return html.Div("無搜尋結果，請嘗試其他地址或增加預算。", style={"color": "#777", "textAlign": "center", "fontWeight": "bold"}), ""

    page = page or 0
    start, end = page * PAGE_SIZE, (page + 1) * PAGE_SIZE
    page_options = all_options[start:end]
    selected_values = selected_values or []

    cards = []
    for opt in page_options:
        pid = opt["value"]
        p = all_details.get(pid, {})
        photo_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=180&photo_reference={p.get('photo_reference')}&key={API_KEY}" if p.get("photo_reference") else None

        cards.append(html.Div([
            dcc.Checklist(
                options=[{"label": "", "value": pid}],
                value=[pid] if pid in selected_values else [],
                id={"type": "place-check", "index": pid},
                style={"marginRight": "8px","backgroundColor": "#fff","boxShadow": "0 6px 16px rgba(0,0,0,0.12)","border": "1px solid rgba(0,0,0,0.06)"}
            ),
            html.Img(src=photo_url, style={"width": "100px", "height": "100px", "objectFit": "cover", "borderRadius": "4px", "marginRight": "10px"}) if photo_url else None,
            html.Div([
                html.Div([
                    html.Strong(p.get("name"), style={"fontSize": 17}),
                    html.Span(f" ｜ 熱門程度 {p.get('popularity_score', 0)}", style={"color": "#ffa000", "marginLeft": "4px"})
                ]),
                html.Div(f"地址：{p.get('vicinity', '無')}", style={"color": "#555", "fontSize": 14}),
                html.Div(f"評分：{p.get('rating', '無')} ｜ 距離：{p.get('distance_km', 0):.2f} km", style={"color": "#777", "fontSize": 13}),
                html.Button("查看詳情", id={"type": "detail-btn", "index": pid}, style={"marginTop": "4px", "fontSize": 13, "padding": "2px 8px"})
            ], style={"width": "calc(100% - 130px)"})
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px", "borderBottom": "1px solid #eee", "paddingBottom": "10px"}))

    max_page = max((len(all_options) - 1) // PAGE_SIZE + 1, 1)
    return cards, f"第 {page + 1} / {max_page} 頁"

@app.callback(
    Output("page", "data", allow_duplicate=True),
    Input("prev-page", "n_clicks"),
    Input("next-page", "n_clicks"),
    State("page", "data"),
    State("all-options", "data"),
    prevent_initial_call=True,
)
def change_page(prev, next, page, options):
    if not options: return no_update
    ctx = callback_context
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    max_p = (len(options) - 1) // PAGE_SIZE
    page = page or 0
    if trigger == "prev-page": page = max(page - 1, 0)
    elif trigger == "next-page": page = min(page + 1, max_p)
    return page

@app.callback(
    Output("place-selector", "value", allow_duplicate=True),
    Input({"type": "place-check", "index": ALL}, "value"),
    Input({"type": "remove-btn", "index": ALL}, "n_clicks"),
    Input({"type": "move-up", "index": ALL}, "n_clicks"),
    Input({"type": "move-down", "index": ALL}, "n_clicks"),
    State("place-selector", "value"),
    prevent_initial_call=True,
)
def sync_selection(checks, removes, ups, downs, current):
    ctx = callback_context
    if not ctx.triggered: return no_update
    trigger_id = json.loads(ctx.triggered[0]["prop_id"].split(".")[0])
    pid, action = trigger_id["index"], trigger_id["type"]
    current = list(current or [])

    if action == "place-check":
        val = ctx.triggered[0]["value"]
        if val and pid not in current: current.append(pid)
        elif not val and pid in current: current.remove(pid)
    elif action == "remove-btn" and pid in current:
        current.remove(pid)
    elif action in ["move-up", "move-down"] and pid in current:
        idx = current.index(pid)
        swap_idx = idx - 1 if action == "move-up" else idx + 1
        if 0 <= swap_idx < len(current):
            current[idx], current[swap_idx] = current[swap_idx], current[idx]
    return current


@app.callback(
    Output("manual-budget-store", "data"),
    Output("budget-warning", "children"),
    Output("budget-progress-bar", "style"),
    Input({"type": "budget-input", "index": ALL}, "value"),
    Input("place-selector", "value"),
    Input("total-trip-budget", "value"),
    Input("budget", "value"),
    State({"type": "budget-input", "index": ALL}, "id"),
    State("manual-budget-store", "data"),
    State("all-place-details", "data"),
)
def update_budget_logic(input_vals, selected, total_trip_limit, single_budget_limit, input_ids, store, all_details):
    store = store or {}
    total_trip_limit = total_trip_limit if total_trip_limit is not None else 0
    single_budget_limit = single_budget_limit if single_budget_limit is not None else 0
    
    # 1. 處理手動輸入
    if callback_context.triggered:
        trigger_prop = callback_context.triggered[0]["prop_id"]
        if "budget-input" in trigger_prop:
            for val, id_obj in zip(input_vals, input_ids):
                store[id_obj["index"]] = val if val is not None else 0

    # 2. 自動估算新加入的地點預算
    level_price_map = {1: 200, 2: 600, 3: 1000, 4: 2000}
    if selected and all_details:
        for pid in selected:
            if pid not in store:
                pl = all_details.get(pid, {}).get("price_level_int")
                store[pid] = level_price_map.get(pl, 200) if pl is not None else 200

    # 3. 計算分配總額與檢查「單點超支」
    current_allocated_total = 0
    violation_count = 0
    if selected:
        for pid in selected:
            cost = store.get(pid, 0)
            current_allocated_total += cost
            if cost > single_budget_limit:
                violation_count += 1

    remaining_budget = total_trip_limit - current_allocated_total
    
    # --- 關鍵修正：調整判斷順序 ---
    # 1. 最優先判斷：總預算是否超支 (顯示紅色)
    if remaining_budget < 0:
        color = "#d9534f" # 警告紅
        status_text = f"⚠️ 已超出總預算 {abs(remaining_budget):.0f} 元"
        if violation_count > 0:
            status_text += f" (且有 {violation_count} 處超出單點限制)"

    # 2. 次要判斷：雖然總額沒超，但有單點預算超支 (顯示橘色)
    elif violation_count > 0:
        color = "#f20418" # 警告橘
        status_text = f"🚨 提醒：有 {violation_count} 個地點超過單點預算限制"

    # 3. 判斷：預算剛好花完 (顯示藍色/橘色)
    elif remaining_budget == 0 and total_trip_limit > 0:
        color = "#5bc0de" 
        status_text = "🎯 預算已全數分配完畢"

    # 4. 最後判斷：兩者皆符合，正常剩餘 (顯示綠色)
    else:
        color = "#28a745" # 成功綠
        status_text = f"💰 總預算剩餘 {remaining_budget:.0f} 元"

    # 重新設計提示語 UI
    msg = html.Div([
        html.Div([
            html.Span(f"目前已規劃支出：{current_allocated_total:.0f} 元", style={"marginRight": "15px"}),
            html.Span(f"{status_text}", style={"fontWeight": "bold", "fontSize": "18px"})
        ]),
    ], style={
        "color": color, 
        "padding": "12px", 
        "backgroundColor": f"{color}11", 
        "border": f"2px solid {color}",
        "borderRadius": "8px",
        "marginTop": "10px",
        "transition": "all 0.3s"
    })
    
    # 計算進度條寬度
    progress_width = 0
    if total_trip_limit > 0:
        progress_width = min((current_allocated_total / total_trip_limit) * 100, 100)
    
    progress_style = {
        "width": f"{progress_width}%",
        "height": "100%",
        "backgroundColor": "#458a4b",
        "borderRadius": "999px",
        "transition": "width 0.3s ease"
    }
    
    return store, msg, progress_style

@app.callback(
    Output("selected-itinerary", "children"),
    Input("place-selector", "value"),
    State("manual-budget-store", "data"),
    State("all-place-details", "data"),
)
def render_selected(selected, budgets, details):
    if not selected: 
        return html.Div("尚未選擇任何地點", style={"color": "#999", "textAlign": "center", "padding": "40px", "fontWeight": "bold"})
        return html.Div("尚未選擇任何地點。", style={"color": "#777"})
    items = []
    budgets = budgets or {}
    details = details or {}
    
    # 備援渲染對照表
    level_price_map = {1: 200, 2: 600, 3: 1000, 4: 2000}

    for i, pid in enumerate(selected):
        p = details.get(pid, {})
        
        # 決定顯示在 Input 框內的金額
        if pid in budgets:
            # 優先使用 Store 裡已算好或改過的值
            cost = budgets[pid]
        else:
            # 沒資料時按等級計算（未知 = 200）
            pl = p.get("price_level_int")
            cost = level_price_map.get(pl, 200) if pl is not None else 200

        items.append(html.Li([
            html.Div([
                html.Span(f"{i+1}. {p.get('name')}", style={"fontWeight": "bold"}),
                html.Div([
                    html.Button("↑", id={"type": "move-up", "index": pid}, style={"padding": "4px 10px", "backgroundColor": "#56602D", "color": "white", "border": "none", "borderRadius": "999px", "cursor": "pointer", "marginLeft": "5px"}),
                    html.Button("↓", id={"type": "move-down", "index": pid}, style={"padding": "4px 10px", "backgroundColor": "#56602D", "color": "white", "border": "none", "borderRadius": "999px", "cursor": "pointer", "marginLeft": "5px"}),
                ], style={"float": "right"})
            ]),
            html.Div([
                html.Span("預算: "),
                # 這裡的 value={cost} 會反映 200/600/1000 等自動填入值
                dcc.Input(
                    id={"type": "budget-input", "index": pid}, 
                    type="number", 
                    value=cost, 
                    debounce=True, 
                    style={"width": "80px"}
                ),
                html.Button("移除", id={"type": "remove-btn", "index": pid}, style={"marginLeft":"10px", "fontSize":12, "padding": "4px 12px", "backgroundColor": "#56602D", "color": "white", "border": "none", "borderRadius": "999px", "cursor": "pointer"})
            ], style={"marginTop": "5px"}),
        ], style={"marginBottom": "10px", "borderBottom": "1px solid #eee", "paddingBottom": "5px"}))
    
    return html.Ol(items, style={"paddingLeft": "0px", "listStyleType": "none"})

@app.callback(
    Output("budget-pie-chart", "figure"),
    Output("category-pie-chart", "figure"),
    Input("place-selector", "value"),
    Input("manual-budget-store", "data"),
    State("budget", "value"),
    State("all-place-details", "data"),
)
def update_charts(selected, budgets, total_budget, details):
    empty = {'data': [], 'layout': {'title': '無資料'}}
    if not selected: return empty, empty
    budgets = budgets or {}
    labels, values, types = [], [], {}
    spent = 0
    for pid in selected:
        name = details.get(pid, {}).get("name", "未知")
        cost = budgets.get(pid, 0)
        labels.append(name)
        values.append(cost)
        spent += cost
        t = details.get(pid, {}).get("primary_type", "其他")
        types[t] = types.get(t, 0) + 1
    if total_budget and (total_budget - spent) > 0:
        labels.append("剩餘預算")
        values.append(total_budget - spent)
    fig_budget = {'data': [{'type': 'pie', 'labels': labels, 'values': values, 'hole': .3, 'textinfo': 'label'}], 'layout': {'title': f"預算分配 (總計: {spent})", 'margin': {'t':40, 'b':10}}}
    fig_type = {'data': [{'type': 'pie', 'labels': list(types.keys()), 'values': list(types.values()), 'hole': .3}], 'layout': {'title': "行程類型分佈", 'margin': {'t':40, 'b':10}}}
    return fig_budget, fig_type

@app.callback(
    Output("modal-trigger-state", "data"),
    Input({"type": "detail-btn", "index": ALL}, "n_clicks"),
    Input("detail-backdrop", "n_clicks"),
    Input({"type": "close-detail", "index": ALL}, "n_clicks"),
    State("modal-trigger-state", "data"),
    prevent_initial_call=True,
)
def toggle_modal(btn, backdrop, close, state):
    ctx = callback_context
    if not ctx.triggered: return no_update
    trigger_prop = ctx.triggered[0]["prop_id"]
    trigger_val = ctx.triggered[0]["value"]
    if "detail-backdrop" in trigger_prop or "close-detail" in trigger_prop:
        return {"open": False, "pid": None}
    if "detail-btn" in trigger_prop:
        if not trigger_val or trigger_val <= 0: return no_update
        try:
            pid = json.loads(trigger_prop.split(".")[0])["index"]
            if state.get("pid") != pid or not state.get("open"):
                return {"open": True, "pid": pid}
        except: return no_update
    return no_update

@app.callback(
    Output("detail-modal", "style"),
    Output("detail-backdrop", "style"),
    Output("detail-modal", "children"),
    Output("detail-cache", "data"),
    Input("modal-trigger-state", "data"),
    State("detail-cache", "data"),
)
def render_modal_content(state, cache):
    if not state.get("open"):
        return STYLES["modal_content"], STYLES["modal_overlay"], no_update, no_update
    pid = state["pid"]
    cache = cache or {}
    if pid in cache:
        res, reviews = cache[pid]["result"], cache[pid]["reviews"]
    else:
        res, reviews = fetch_place_details(pid)
        cache[pid] = {"result": res, "reviews": reviews}
    open_now = res.get("opening_hours", {}).get("open_now")
    status_text = "✅ 營業中" if open_now else "❌ 休息中" if open_now is False else "未知"
    content = html.Div([
        html.H2(res.get("name"), style={"marginTop": 0}),
        html.P([html.Strong("地址: "), res.get("formatted_address")]),
        html.P([html.Strong("電話: "), res.get("formatted_phone_number", "無")]),
        html.P([html.Strong("狀態: "), html.Span(status_text, style={"color": "green" if open_now else "red"})]),
        html.Hr(),
        html.H4("最新評論"),
        html.Div([
            html.Div([
                html.Strong(r.get("author_name")),
                html.Span(f" ({r.get('rating')}★): "),
                html.Span(r.get("text")[:100] + "...")
            ], style={"marginBottom": "8px", "fontSize": 14}) for r in reviews
        ] if reviews else "暫無評論"),
        html.Button("關閉", id={"type": "close-detail", "index": pid}, style={"float": "right", "marginTop": "10px"})
    ])
    return {**STYLES["modal_content"], "display": "block"}, {**STYLES["modal_overlay"], "display": "block"}, content, cache

# --- 找到程式碼約第 100 行的這一行並「刪除」 ---
# init_db()  <-- 務必刪掉！

# --- 移到程式碼最底部 ---
# --- 檢查點 1：刪除程式碼上半部所有「呼叫」init_db() 的地方 ---
# 確保原本在 init_db() 定義下方的呼叫被刪除了！

# --- 檢查點 2：修改底部的啟動邏輯 ---
if __name__ == "__main__":
    # 檢查檔案是否已存在，避免重複初始化
    if not os.path.exists(DB_NAME):
        init_db()
        print("首次啟動，資料庫已建立。")
    
    # 強制單執行緒模式，關閉重載器，徹底排除併發問題
    app.run(debug=False, threaded=False, use_reloader=False)
