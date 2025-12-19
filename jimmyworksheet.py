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
import os

from flask import Flask, redirect
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# ----------------------------------------------------
# 🔐 設定與資料庫初始化 (SQLite & Flask-Login)
# ----------------------------------------------------

# 初始化 Flask Server 與 Dash
server = Flask(__name__)
server.secret_key = 'CHANGE_THIS_SECRET_KEY_IN_PRODUCTION'  # 用於 Session 加密

app = dash.Dash(__name__, server=server)
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

# 全域 DB 鎖，確保跨 thread 的存取一致性
DB_LOCK = threading.Lock()


def db_connect():
    """回傳可跨 thread 使用的 sqlite3 連線（設為 check_same_thread=False）。
    使用完成後請務必 close()。
    """
    return sqlite3.connect(DB_NAME, check_same_thread=False, timeout=30)

def init_db():
    """初始化資料庫，建立 users 表 + itineraries 表"""
    conn = db_connect()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # ✅ 新增：行程儲存（每個 user_id 一筆）
    c.execute('''
        CREATE TABLE IF NOT EXISTS itineraries (
            user_id INTEGER PRIMARY KEY,
            selected_json TEXT NOT NULL,
            budgets_json TEXT NOT NULL,
            details_json TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # 建立歷史行程表，避免後續 SELECT 在 table 不存在時出錯
    c.execute('''
        CREATE TABLE IF NOT EXISTS itinerary_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT,
            selected_json TEXT NOT NULL,
            budgets_json TEXT,
            details_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    try:
        # 修改這裡：從 WAL 改為 DELETE
        c.execute("PRAGMA journal_mode=DELETE") 
        c.execute("PRAGMA synchronous=FULL") # 確保實體寫入
        print(f"[DEBUG] init_db: journal_mode set to {c.fetchone()}")
    except Exception:
        pass
    conn.close()



# 替換掉原本的 _parse_triggered_id 或新增此函式
def _get_triggered_index(prop_id_str=None):
    """使用 Dash 2.4+ 推薦的 triggered_id 方式，精確抓取 Pattern-matching 的 index"""
    ctx = callback_context
    if not ctx.triggered:
        return None
    # 取得觸發元件的 ID 字典
    t_id = ctx.triggered_id
    if isinstance(t_id, dict):
        return t_id.get('index')
    return None


def _parse_triggered_id(prop_id_str):
    """解析 callback_context 回傳的 prop_id（或傳入的 prop_id 字串），回傳 dict 或 None。
    prop_id_str 可能是字串形式例如 '{"type":"delete-history","index":123}.n_clicks'
    或已經是 dict（某些情況下會直接傳入）。"""
    try:
        if isinstance(prop_id_str, dict):
            return prop_id_str
        # 如果是類似 '... .n_clicks' 的字串，先取前半段再 json.loads
        base = str(prop_id_str).split('.')[0]
        return json.loads(base)
    except Exception:
        return None

# --- 行程儲存/載入工具 ---
def save_user_itinerary(user_id, selected, budgets, details_subset):
    """儲存使用者已選行程（UPSERT）"""
    selected = selected or []
    budgets = budgets or {}
    details_subset = details_subset or {}

    conn = db_connect()
    c = conn.cursor()
    with DB_LOCK:
        c.execute("""
        INSERT INTO itineraries (user_id, selected_json, budgets_json, details_json, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            selected_json = excluded.selected_json,
            budgets_json = excluded.budgets_json,
            details_json = excluded.details_json,
            updated_at = CURRENT_TIMESTAMP
    """, (
        int(user_id),
        json.dumps(selected, ensure_ascii=False),
        json.dumps(budgets, ensure_ascii=False),
        json.dumps(details_subset, ensure_ascii=False),
    ))
        conn.commit()
    conn.close()

def load_user_itinerary(user_id):
    """讀取使用者已選行程；沒有就回空"""
    if not user_id:
        return {"selected": [], "budgets": {}, "details": {}}

    conn = db_connect()
    c = conn.cursor()
    with DB_LOCK:
        c.execute("SELECT selected_json, budgets_json, details_json FROM itineraries WHERE user_id = ?", (int(user_id),))
        row = c.fetchone()
    conn.close()

    if not row:
        return {"selected": [], "budgets": {}, "details": {}}

    try:
        selected = json.loads(row[0]) if row[0] else []
        budgets  = json.loads(row[1]) if row[1] else {}
        details  = json.loads(row[2]) if row[2] else {}
    except Exception:
        selected, budgets, details = [], {}, {}

    return {"selected": selected, "budgets": budgets, "details": details}


# --- 多筆歷史行程表（每個使用者可儲存多筆） -----------------
def add_history_itinerary(user_id, selected, budgets, details_subset, title=None):
    selected = selected or []
    budgets = budgets or {}
    details_subset = details_subset or {}

    conn = db_connect()
    c = conn.cursor()
    # （表在 init_db 已建立；這裡保留以防 DB 被移除）
    with DB_LOCK:
        c.execute('''
        CREATE TABLE IF NOT EXISTS itinerary_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT,
            selected_json TEXT NOT NULL,
            budgets_json TEXT,
            details_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    try:
        with DB_LOCK:
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
            inserted = c.lastrowid
            conn.commit()
            print(f"[DEBUG] add_history_itinerary: DB={DB_NAME} inserted id={inserted} for user={user_id}, selected_count={len(selected)}")
            # 立即讀取確認（debug helper）
            try:
                c.execute("SELECT COUNT(*) FROM itinerary_history")
                cnt = c.fetchone()
                c.execute("SELECT id, user_id, title, created_at FROM itinerary_history ORDER BY id DESC LIMIT 5")
                recent = c.fetchall()
                try:
                    c.execute("PRAGMA database_list")
                    dbl = c.fetchall()
                except Exception:
                    dbl = None
                # 強制 checkpoint 一次，讓其他連線能更快看到變更
                try:
                    c.execute("PRAGMA wal_checkpoint(FULL)")
                    cp = c.fetchone()
                except Exception:
                    cp = None
                print(f"[DEBUG] add_history_itinerary: post-insert count={cnt}, recent={recent}, database_list={dbl}, checkpoint={cp}, in_transaction={conn.in_transaction}, pid={os.getpid()}, thread={threading.get_ident()}")
            except Exception as e:
                print(f"[ERROR] add_history_itinerary: post-insert verification failed: {e}")
    except Exception as e:
        print(f"[ERROR] add_history_itinerary failed: {e}")
    finally:
        conn.close()


def load_user_itineraries(user_id):
    """回傳該使用者所有歷史行程（由新到舊）"""
    if not user_id:
        print(f"[DEBUG] load_user_itineraries called with falsy user_id: {user_id!r}")
        return []
    conn = db_connect()
    c = conn.cursor()
    try:
        c.execute("PRAGMA database_list")
        dbl = c.fetchall()
    except Exception:
        dbl = None
    print(f"[DEBUG] load_user_itineraries: connecting to DB={DB_NAME}, database_list={dbl}, conn_in_transaction={conn.in_transaction}, pid={os.getpid()}, thread={threading.get_ident()}")
    try:
        with DB_LOCK:
            c.execute("SELECT id, title, selected_json, budgets_json, details_json, created_at FROM itinerary_history WHERE user_id = ? ORDER BY created_at DESC", (int(user_id),))
            rows = c.fetchall()
        print(f"[DEBUG] load_user_itineraries: DB={DB_NAME} fetched_rows={len(rows)} for user={user_id!r} (type={type(user_id)}), pid={os.getpid()}, thread={threading.get_ident()}, total_changes={conn.total_changes}")
        if rows:
            print(f"[DEBUG] sample_row_ids: {[r[0] for r in rows[:5]]}")
        else:
            # 若查無，印出最近幾筆以供比對（不會回傳給呼叫端）
            try:
                with DB_LOCK:
                    c.execute("SELECT id, user_id, title, created_at FROM itinerary_history ORDER BY id DESC LIMIT 10")
                    recent = c.fetchall()
                print(f"[DEBUG] load_user_itineraries: recent rows (any user): {recent}")
            except Exception as e:
                print(f"[ERROR] load_user_itineraries: failed to fetch recent rows: {e}")
    except Exception as e:
        print(f"[ERROR] load_user_itineraries: query failed: {e}")
        rows = []
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            sel = json.loads(r[2]) if r[2] else []
            budgets = json.loads(r[3]) if r[3] else {}
            details = json.loads(r[4]) if r[4] else {}
        except Exception:
            sel, budgets, details = [], {}, {}
        out.append({"id": r[0], "title": r[1], "selected": sel, "budgets": budgets, "details": details, "created_at": r[5]})
    return out


def delete_itinerary_history(entry_id, user_id):
    conn = db_connect()
    c = conn.cursor()
    with DB_LOCK:
        c.execute("DELETE FROM itinerary_history WHERE id = ? AND user_id = ?", (int(entry_id), int(user_id)))
        conn.commit()
    conn.close()


def get_history_entry(entry_id, user_id):
    conn = sqlite3.connect(DB_NAME, timeout=30)
    c = conn.cursor()
    try:
        # 改成只查 ID，不要管 user_id，看看能不能抓到
        c.execute("SELECT id, title, selected_json, budgets_json, details_json, created_at FROM itinerary_history WHERE id = ?", (int(entry_id),))
        row = c.fetchone()
        if row:
            print(f"[DEBUG] get_history_entry SUCCESS by ID={entry_id}")
            return {
                "id": row[0], "title": row[1],
                "selected": json.loads(row[2]),
                "budgets": json.loads(row[3]),
                "details": json.loads(row[4]),
                "created_at": row[5]
            }
        else:
            print(f"[CRITICAL ERROR] ID={entry_id} COMPLETELY GONE FROM DB FILE!")
            return None
    finally:
        conn.close()

    # 若查無，嘗試以 id 單獨搜尋並印出比對資訊，協助除錯
    if not row:
        try:
            with DB_LOCK:
                c.execute("SELECT id, user_id, title, selected_json, budgets_json, details_json, created_at FROM itinerary_history WHERE id = ?", (int(entry_id),))
                fallback = c.fetchone()
            print(f"[ERROR] get_history_entry: 找不到資料! ID={entry_id}, User={user_id}")
            print(f"[DEBUG] get_history_entry: attempted params={params}, fallback_by_id={fallback}")
        except Exception as e:
            print(f"[ERROR] get_history_entry: fallback query failed: {e}")
        finally:
            conn.close()
        return None

    conn.close()
    
    # 解析 JSON... (保留原本邏輯)
    try:
        sel = json.loads(row[2])
        budgets = json.loads(row[3])
        details = json.loads(row[4])
    except:
        sel, budgets, details = [], {}, {}
        
    return {"id": row[0], "title": row[1], "selected": sel, "budgets": budgets, "details": details, "created_at": row[5]}

# --- 使用者模型 (配合 Flask-Login) ---
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = db_connect()
    c = conn.cursor()
    with DB_LOCK:
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
    API_KEY = ""

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
        "display": "flex", "flexWrap": "wrap", "alignItems": "center", "gap": "8px", "marginBottom": "10px",
    },
    "input_text": {"fontSize": 16, "width": "320px", "padding": "6px 8px"},
    "input_budget": {"fontSize": 16, "width": "180px", "padding": "6px 8px"},
    "btn_primary": {
        "fontSize": 16, "padding": "8px 20px", "backgroundColor": "#1976D2",
        "color": "white", "border": "none", "borderRadius": "4px", "cursor": "pointer",
    },
    "card_container": {
        "border": "1px solid #ddd", "borderRadius": "4px", "padding": "10px",
        "maxHeight": "450px", "overflowY": "auto", "backgroundColor": "#fafafa",
    },
    "modal_overlay": {
        "position": "fixed", "top": 0, "left": 0, "width": "100vw", "height": "100vh",
        "backgroundColor": "rgba(0,0,0,0.3)", "zIndex": 999, "display": "none"
    },
    "modal_content": {
        "position": "fixed", "top": "50%", "left": "50%", "transform": "translate(-50%, -50%)",
        "backgroundColor": "white", "border": "1px solid #ccc", "borderRadius": "6px",
        "padding": "16px", "boxShadow": "0 2px 8px rgba(0,0,0,0.3)",
        "zIndex": 1000, "width": "420px", "maxHeight": "70vh", "overflowY": "auto",
        "display": "none"
    },
    # 新增登入頁面樣式
    "auth_container": {
        "width": "300px", "margin": "100px auto", "padding": "30px",
        "border": "1px solid #ccc", "borderRadius": "10px", "textAlign": "center",
        "boxShadow": "0 4px 12px rgba(0,0,0,0.1)"
    },
    "auth_input": {
        "width": "100%", "padding": "10px", "marginBottom": "15px",
        "boxSizing": "border-box", "borderRadius": "5px", "border": "1px solid #ddd"
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
            primary_type = "美食" if k == "food" else "娛樂/逛街"
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
        # Header: 顯示使用者與登出按鈕
        html.Div([
            html.Span(f"👋 Hi, {username}", style={"fontWeight": "bold", "marginRight": "15px"}),
            dcc.Link(html.Button("登出", style={"fontSize": "14px", "padding": "4px 10px", "cursor": "pointer"}), href="/logout"),
        ], style={"textAlign": "right", "marginBottom": "10px"}),

        dcc.Loading(
            id="loading-search", type="circle", fullscreen=True, color="#0B16EA",
            style={"transform": "scale(2)"}, children=dcc.Store(id="loading-trigger-store")
        ),

        html.Div([
            html.H1("附近行程智慧推薦", style={"marginBottom": "5px"}),
            html.P("輸入出發地與預算，系統將為您推薦最佳行程。", style={"marginTop": "0px", "color": "#555"}),
        ], style={"textAlign": "left", "marginBottom": "20px"}),

        html.Div([
            dcc.Input(
                id="address", type="text", placeholder="輸入出發地址，例如：台北車站", style=STYLES["input_text"]
            ),
            dcc.Input(
                id="budget", type="number", placeholder="預算上限 (TWD)", value=1000, style=STYLES["input_budget"]
            ),
            dcc.Dropdown(
                id="category",
                options=[{"label": "美食", "value": "food"}, {"label": "娛樂 / 逛街", "value": "fun"}],
                value=["food", "fun"],
                multi=True, clearable=False,
                style={"width": "260px", "verticalAlign": "middle"}
            ),
            html.Button("查詢", id="search-btn", n_clicks=0, style=STYLES["btn_primary"]),
        ], style=STYLES["input_group"]),

        html.Div(id="budget-warning", style={"marginTop": "5px", "marginBottom": "15px", "fontSize": 16}),

        html.Div([
            html.Div([
                html.H3("推薦地點", style={"marginBottom": "10px"}),
                html.Div(
                    id="result-container",
                    children=html.Div("請輸入地址並查詢...", style={"color": "#777"}),
                    style=STYLES["card_container"]
                ),
                html.Div([
                    html.Button("上一頁", id="prev-page", n_clicks=0, style={"marginRight": "10px"}),
                    html.Span(id="page-info", style={"marginRight": "10px"}),
                    html.Button("下一頁", id="next-page", n_clicks=0),
                ], style={"marginTop": "10px"}),
            ], style={"flex": "2", "marginRight": "20px"}),

            html.Div([
                html.Div([
                    html.H3("已選行程", style={"marginBottom": "10px", "display": "inline-block", "marginRight": "10px"}),
                    html.Button("儲存行程並查看歷史", id="save-itinerary-btn", n_clicks=0, style={"fontSize": 13, "padding": "6px 10px"}),
                ], style={"display": "flex", "alignItems": "center", "justifyContent": "space-between"}),
                html.Div(
                    id="selected-itinerary",
                    style={**STYLES["card_container"], "backgroundColor": "#fff", "minHeight": "80px"}
                ),
            ], style={"flex": "1"}),
        ], style={"display": "flex", "flexDirection": "row", "marginBottom": "20px"}),

        html.Div([
            html.H3("行程分析", style={"marginBottom": "10px"}),
            html.Div([
                dcc.Graph(id="budget-pie-chart", style={"width": "50%"}, config={"displayModeBar": False}),
                dcc.Graph(id="category-pie-chart", style={"width": "50%"}, config={"displayModeBar": False}),
            ], style={"display": "flex"}),
        ], style={"borderTop": "1px solid #eee", "paddingTop": "20px"}),

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
                        html.Div([
                            html.Button("查看", id={"type": "view-history", "index": h.get('id')}, n_clicks=0, style={"padding": "6px 8px", "marginRight": "6px"}),
                            html.Button("載入", id={"type": "load-history", "index": h.get('id')}, n_clicks=0, style={"padding": "6px 8px", "marginRight": "6px", "backgroundColor": "#1890ff", "color": "#fff", "border": "none"}),
                            html.Button("刪除", id={"type": "delete-history", "index": h.get('id')}, n_clicks=0, style={"backgroundColor": "#ff4d4f", "color": "#fff", "border": "none", "padding": "6px 8px"}),
                        ])
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
                    html.H2("我的歷史行程", style={"marginBottom": "12px"}),
                    grid,
                    # 詳細 modal（會由 callback 控制顯示/內容）
                    html.Div(id='history-detail-backdrop', style={**STYLES.get("modal_overlay", {}), "display": "none"}),
                    html.Div(id='history-detail-modal', style={**STYLES.get("modal_content", {}), "display": "none"}),
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
def login_callback(n_clicks, username, password):
    if not username or not password:
        return no_update, "請輸入帳號密碼"

    conn = db_connect()
    c = conn.cursor()
    with DB_LOCK:
        c.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
        user_data = c.fetchone()
    conn.close()

    if user_data and check_password_hash(user_data[2], password):
        user = User(id=user_data[0], username=user_data[1])
        login_user(user)
        return '/', ""  # 登入成功，跳轉回首頁
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
    with DB_LOCK:
        c.execute("SELECT id FROM users WHERE username = ?", (username,))
        if c.fetchone():
            conn.close()
            return no_update, "帳號已存在"

        hashed_pw = generate_password_hash(password)
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pw))
        conn.commit()
    conn.close()

    return '/login', ""  # 註冊成功，跳轉登入頁

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
    ctx = callback_context
    if not ctx.triggered:
        return no_update
    triggered_prop = ctx.triggered[0].get('prop_id')
    parsed = _parse_triggered_id(triggered_prop)
    if not parsed:
        return no_update
    try:
        entry_id = int(parsed.get('index')) if parsed.get('index') is not None else None
    except Exception:
        entry_id = parsed.get('index')

    if not current_user.is_authenticated:
        return '/login'

    delete_itinerary_history(entry_id, current_user.id)
    return '/history'


# 顯示歷史行程細節（modal）
@app.callback(
    [Output('history-detail-modal', 'style'),
     Output('history-detail-backdrop', 'style'),
     Output('history-detail-modal', 'children')],
    [Input({'type': 'view-history', 'index': ALL}, 'n_clicks')],
    prevent_initial_call=True,
)
def show_history_detail(n_clicks_list):
    try:
        # 事實檢查：確認是否有按鈕被點擊
        if not any(n_clicks for n_clicks in n_clicks_list if n_clicks):
            return no_update, no_update, no_update

        entry_id = _get_triggered_index() # 使用新的解析函式
        if entry_id is None:
            return no_update, no_update, no_update

        if not current_user.is_authenticated:
            return no_update, no_update, "請先登入"

        # 先嘗試使用 load_user_itineraries（已在其他地方使用且正確返回），避免直接 DB 單筆查詢的 race-condition
        try:
            histories = load_user_itineraries(current_user.id)
            target = next((h for h in histories if h.get('id') == int(entry_id)), None)
            print(f"[DEBUG] show_history_detail: searched in load_user_itineraries, found={bool(target)} for id={entry_id}")
        except Exception as e:
            print(f"[ERROR] show_history_detail: load_user_itineraries failed: {e}")
            target = None

        # 若仍找不到，才使用單筆查詢作為最後手段（並會在 get_history_entry 中有詳細備援輸出）
        if not target:
            # 嘗試重試數次以容許短暫的一致性延遲
            import time
            target = None
            for attempt in range(1, 4):
                target = get_history_entry(int(entry_id), int(current_user.id))
                print(f"[DEBUG] show_history_detail: retry attempt={attempt}, found={bool(target)} for id={entry_id}")
                if target:
                    break
                time.sleep(0.1)

        if not target:
            return no_update, no_update, "找不到該筆行程"

        # 重新構建 Modal 內容，確保關閉按鈕的 ID 被正確生成
        sel = target.get('selected', [])
        details = target.get('details', {})
        items = []
        for i, pid in enumerate(sel):
            d = details.get(pid, {})
            items.append(html.Div([
                html.Strong(f"{i+1}. {d.get('name', pid)}"),
                html.Div(f"地址: {d.get('vicinity', '無')}", style={"fontSize": "13px", "color": "#666"})
            ], style={"marginBottom": "10px", "paddingBottom": "5px", "borderBottom": "1px solid #eee"}))

        content = html.Div([
            html.H2(target.get('title', '歷史行程詳情'), style={"marginTop": "0"}),
            html.Div(f"建立時間：{target.get('created_at', '')}", style={"color": "#999", "fontSize": "12px", "marginBottom": "15px"}),
            html.Div(items if items else "無內容", style={"maxHeight": "400px", "overflowY": "auto"}),
            html.Hr(),
            html.Button("關閉視窗", id={'type': 'close-history-detail', 'index': entry_id}, 
                        n_clicks=0, style={**STYLES["btn_primary"], "backgroundColor": "#555", "float": "right"})
        ])

        # 明確回傳顯示狀態
        modal_style = {**STYLES.get('modal_content', {}), 'display': 'block'}
        overlay_style = {**STYLES.get('modal_overlay', {}), 'display': 'block'}
        return modal_style, overlay_style, content
    except Exception as e:
        print(f"[ERROR] show_history_detail exception: {e}")
        import traceback
        traceback.print_exc()
        return no_update, no_update, no_update

    # Build detail content
    sel = target.get('selected', [])
    details = target.get('details', {})
    items = []
    for i, pid in enumerate(sel):
        d = details.get(pid, {})
        items.append(html.Div([
            html.Strong(f"{i+1}. {d.get('name', pid)}"),
            html.Div(f"地址: {d.get('vicinity', '無')}")
        ], style={"marginBottom": "8px"}))

    content = html.Div([
        html.H2(target.get('title', '歷史行程詳情')),
        html.Div(f"建立時間：{target.get('created_at', '')}", style={"color": "#777", "marginBottom": "8px"}),
        html.Div(items or "無內容"),
        html.Button("關閉", id={'type': 'close-history-detail', 'index': entry_id}, n_clicks=0, style={"float": "right", "marginTop": "10px"})
    ], style={"maxHeight": "70vh", "overflowY": "auto"})

    return {**STYLES.get('modal_content', {}), 'display': 'block'}, {**STYLES.get('modal_overlay', {}), 'display': 'block'}, content


# 關閉歷史詳情 modal
@app.callback(
    [Output('history-detail-modal', 'style', allow_duplicate=True),
     Output('history-detail-backdrop', 'style', allow_duplicate=True)],
    [Input({'type': 'close-history-detail', 'index': ALL}, 'n_clicks'),
     Input('history-detail-backdrop', 'n_clicks')],
    prevent_initial_call=True,
)
def close_history_detail(close_clicks, backdrop_clicks):
    # 無論觸發哪個，都回傳隱藏樣式
    hidden_modal = {**STYLES.get('modal_content', {}), 'display': 'none'}
    hidden_overlay = {**STYLES.get('modal_overlay', {}), 'display': 'none'}
    return hidden_modal, hidden_overlay


# 載入歷史行程到主頁（保存為目前選取，然後導回主頁）
@app.callback(
    Output('url', 'pathname', allow_duplicate=True),
    Input({'type': 'load-history', 'index': ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def load_history_to_main(n_clicks_list):
    ctx = callback_context
    if not ctx.triggered:
        return no_update
    triggered_prop = ctx.triggered[0].get('prop_id')
    parsed = _parse_triggered_id(triggered_prop)
    if not parsed:
        return no_update
    try:
        entry_id = int(parsed.get('index')) if parsed.get('index') is not None else None
    except Exception:
        entry_id = parsed.get('index')

    if not current_user.is_authenticated:
        return '/login'

    histories = load_user_itineraries(current_user.id)
    target = next((h for h in histories if h.get('id') == entry_id), None)
    if not target:
        return no_update

    # 將該歷史項目儲存為目前使用者的 selected（覆蓋），之後回到主頁以載入
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
        return html.Div("無搜尋結果，請嘗試其他地址或增加預算。", style={"color": "#777"}), ""

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
                style={"marginRight": "8px"}
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
    Input({"type": "budget-input", "index": ALL}, "value"),
    Input("place-selector", "value"),
    State({"type": "budget-input", "index": ALL}, "id"),
    State("manual-budget-store", "data"),
    State("budget", "value"),
    State("all-place-details", "data"),
)
def update_budget_logic(input_vals, selected, input_ids, store, total_budget, all_details):
    store = store or {}
    if callback_context.triggered:
        trigger_prop = callback_context.triggered[0]["prop_id"]
        if "budget-input" in trigger_prop:
            for val, id_obj in zip(input_vals, input_ids):
                store[id_obj["index"]] = val if val is not None else 0

    current_total = sum(store.get(pid, 0) for pid in (selected or []))
    level_price_map = {1: 200, 2: 400, 3: 1000, 4: 2000}
    if selected and all_details:
        for pid in selected:
            if pid not in store:
                pl = all_details.get(pid, {}).get("price_level_int", 1)
                est = level_price_map.get(pl, 200)
                store[pid] = est
                current_total += est
    color = "red" if total_budget and current_total > total_budget else "green"
    msg = f"目前分配預算約 {current_total:.0f}，{'已超出' if color=='red' else '在'} 預算 {total_budget or 0} 範圍內。"
    return store, html.Span(msg, style={"color": color, "fontWeight": "bold"})

@app.callback(
    Output("selected-itinerary", "children"),
    Input("place-selector", "value"),
    State("manual-budget-store", "data"),
    State("all-place-details", "data"),
)
def render_selected(selected, budgets, details):
    if not selected: return html.Div("尚未選擇任何地點。", style={"color": "#777"})
    items = []
    budgets = budgets or {}
    for i, pid in enumerate(selected):
        p = details.get(pid, {})
        cost = budgets.get(pid, 200)
        items.append(html.Li([
            html.Div([
                html.Span(f"{i+1}. {p.get('name')}", style={"fontWeight": "bold"}),
                html.Div([
                    html.Button("↑", id={"type": "move-up", "index": pid}, style={"padding": "0 5px"}),
                    html.Button("↓", id={"type": "move-down", "index": pid}, style={"padding": "0 5px"}),
                ], style={"float": "right"})
            ]),
            html.Div([
                html.Span("預算: "),
                dcc.Input(id={"type": "budget-input", "index": pid}, type="number", value=cost, debounce=True, style={"width": "80px"}),
                html.Button("移除", id={"type": "remove-btn", "index": pid}, style={"marginLeft":"10px", "color":"red", "fontSize":12})
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
