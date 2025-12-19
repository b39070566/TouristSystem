import dash
from dash import dcc, html, Output, Input, State, no_update, callback_context
from dash.dependencies import ALL
import requests
import json
import math
import sqlite3
import os
from datetime import datetime

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
DB_NAME = "users.db"

def init_db():
    """初始化資料庫，建立 users 表 + itineraries 表"""
    conn = sqlite3.connect(DB_NAME)
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

    conn.commit()
    conn.close()

init_db()

# --- 行程儲存/載入工具 ---
def save_user_itinerary(user_id, selected, budgets, details_subset):
    """儲存使用者已選行程（UPSERT）"""
    selected = selected or []
    budgets = budgets or {}
    details_subset = details_subset or {}

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
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

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
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

# --- 使用者模型 (配合 Flask-Login) ---
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    if res:
        return User(id=res[0], username=res[1])
    return None

# ----------------------------------------------------
# 🔧 原本 easier.py 的設定與常數
# ----------------------------------------------------

# ⚠️ 請注意：這組 Key 建議不要公開上傳至 GitHub
API_KEY = "AI"

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

def normalize_score(value, min_val, max_val):
    if max_val == min_val: return 0
    return 1 - (value - min_val) / (max_val - min_val)

def calculate_weighted_score(places_list, distance_weight=0.5, price_weight=0.5):
    if not places_list: return []
    valid_distances = [p["distance_km"] for p in places_list if p["distance_km"] != float("inf")]
    valid_prices = [p["price_level_int"] for p in places_list if p["price_level_int"] is not None]

    min_dist, max_dist = (min(valid_distances), max(valid_distances)) if valid_distances else (0, 1)
    min_price, max_price = (min(valid_prices), max(valid_prices)) if valid_prices else (1, 4)

    for place in places_list:
        d_score = normalize_score(place["distance_km"], min_dist, max_dist) if place["distance_km"] != float("inf") else 0
        p_score = normalize_score(place["price_level_int"], min_price, max_price) if place["price_level_int"] is not None else 0.5
        weighted = (d_score * distance_weight + p_score * price_weight) * 100
        place["weighted_score"] = round(weighted, 2)

    return sorted(places_list, key=lambda x: x["weighted_score"], reverse=True)

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
                html.H3("已選行程", style={"marginBottom": "10px"}),
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

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
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

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

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
@app.callback(
    Output("itinerary-persist-dummy", "data"),
    Input("place-selector", "value"),
    Input("manual-budget-store", "data"),
    State("all-place-details", "data"),
    prevent_initial_call=True,
)
def persist_itinerary(selected, budgets, all_details):
    if not current_user.is_authenticated:
        return no_update

    selected = selected or []
    budgets = budgets or {}
    all_details = all_details or {}

    # 只存「已選」的 details，避免 DB 爆大
    details_subset = {pid: all_details.get(pid, {}) for pid in selected if pid in all_details}

    try:
        save_user_itinerary(current_user.id, selected, budgets, details_subset)
    except Exception as e:
        print(f"[Persist] save error: {e}")
        return {"ok": False, "error": str(e), "ts": datetime.now().isoformat()}

    return {"ok": True, "ts": datetime.now().isoformat()}

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

    nearby_scored = calculate_weighted_score(nearby)
    max_pl = 1 if budget <= 200 else 2 if budget <= 400 else 3 if budget <= 1400 else 4

    new_details = old_details.copy() if old_details else {}
    options = []

    for p in nearby_scored:
        new_details[p["place_id"]] = p
        pl = p["price_level_int"]
        if pl is None or pl <= max_pl:
            options.append({"label": p.get("name", "未知"), "value": p["place_id"]})

    return options, new_details, options, 0, "done"

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
                    html.Span(f" ｜ 分數 {p.get('weighted_score', 0)}", style={"color": "#ffa000", "marginLeft": "4px"})
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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
