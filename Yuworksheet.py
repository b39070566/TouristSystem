import dash
from dash import dcc, html, Output, Input, State, no_update
from dash.dependencies import ALL
import requests
import json
import dash.exceptions
from dash import callback_context 

app = dash.Dash(__name__)

# ----------------------------------------------------
# 📌 關鍵修正 1: 抑制 ID not found in layout 錯誤 (用於動態 ID)
# ----------------------------------------------------
app.config.suppress_callback_exceptions = True 


# 注意：請將此 API_KEY 替換為您自己的 Google Places API Key
API_KEY = ""

CATEGORY_TYPE_MAP = {
    "food": ["restaurant", "cafe", "bar", "bakery"],
    "fun": [
        "amusement_park",
        "aquarium",
        "art_gallery",
        "bowling_alley",
        "casino",
        "museum",
        "night_club",
        "clothing_store",
        "department_store",
        "tourist_attraction",
        "zoo",
        "shopping_mall",
        "shoe_store",
    ],
}

PAGE_SIZE = 10

# 價位等級到估計花費的映射 (TWD/RMB 估算)
def get_estimated_cost(price_level):
    """根據價位等級估計平均花費 (RMB/TWD 估算)"""
    try:
        pl_int = int(price_level) if price_level is not None else None
    except Exception:
        pl_int = None
        
    if pl_int:
        level_price_map = {1: 200, 2: 400, 3: 1000, 4: 2000}
        return level_price_map.get(pl_int, 0)
    return 0
    
# ---------- 工具函式 (Tool Functions) ----------
def get_latlng(address, apikey):
    """將地址轉換為經緯度 (Geocoding)"""
    resp = requests.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": address, "key": apikey},
    ).json()
    if not resp["results"]:
        raise ValueError("無法找到該地址的經緯度")
        
    loc = resp["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


def search_places(lat, lng, apikey, types_list, radius=1000):
    """搜尋附近地點 (Nearby Search)"""
    all_results = []
    seen_ids = set()
    for t in types_list:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
            params={
                "location": f"{lat},{lng}",
                "radius": radius,
                "type": t,
                "key": apikey,
            },
        ).json()
        results = resp.get("results", [])
        for r in results:
            pid = r.get("place_id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                photos = r.get("photos")
                if photos and isinstance(photos, list) and len(photos) > 0:
                    r["photo_reference"] = photos[0].get("photo_reference")
                else:
                    r["photo_reference"] = None
                all_results.append(r)
    return all_results


def price_level_by_budget(budget):
    """根據預算範圍推算最大可接受的價位等級"""
    if budget is None:
        return 4
    if budget <= 200:
        return 1
    elif budget <= 400:
        return 2
    elif budget <= 1400:
        return 3
    else:
        return 4


def calculate_distance(lat1, lng1, lat2, lng2):
    """計算兩個經緯度點之間的距離（公里）"""
    from math import radians, sin, cos, sqrt, atan2

    R = 6371
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def normalize_score(value, min_val, max_val):
    """將數值標準化為 0 到 1 之間的「分數」，越小的值分數越高 (1 - normalized value)"""
    if max_val == min_val:
        return 0
    return 1 - (value - min_val) / (max_val - min_val)


def calculate_weighted_score(
    places_list, user_lat, user_lng, budget, distance_weight=0.5, price_weight=0.5
):
    """計算地點的加權分數"""
    if not places_list:
        return []
        
    for place in places_list:
        lat = place.get("geometry", {}).get("location", {}).get("lat")
        lng = place.get("geometry", {}).get("location", {}).get("lng")
        
        if lat is not None and lng is not None:
            distance = calculate_distance(user_lat, user_lng, lat, lng)
            place["distance_km"] = distance
        else:
            place["distance_km"] = float("inf")
            
        price_level = place.get("price_level")
        try:
            price_level = int(price_level) if price_level is not None else None
        except Exception:
            price_level = None
        place["price_level_int"] = price_level

    valid_distances = [p["distance_km"] for p in places_list if p["distance_km"] != float("inf")]
    valid_prices = [p["price_level_int"] for p in places_list if p["price_level_int"] is not None]

    if not valid_distances:
        min_distance, max_distance = 0, 1  
    else:
        min_distance = min(valid_distances)
        max_distance = max(valid_distances)
        
    if not valid_prices:
        min_price, max_price = 1, 4
    else:
        min_price = min(valid_prices)
        max_price = max(valid_prices)

    for place in places_list:
        distance = place["distance_km"]
        price = place["price_level_int"]

        if distance == float("inf"):
            distance_score = 0
        else:
            distance_score = normalize_score(distance, min_distance, max_distance)

        if price is None:
            price_score = 0.5
        else:
            price_score = normalize_score(price, min_price, max_price)
            
        weighted_score = (distance_score * distance_weight + price_score * price_weight) * 100
        place["weighted_score"] = round(weighted_score, 2)
        
        # 為了類型分類，添加地點類型
        primary_type = "其他"
        place_types = place.get("types", [])
        for k, v in CATEGORY_TYPE_MAP.items():
            if any(t in place_types for t in v):
                if k == "food":
                    primary_type = "美食"
                elif k == "fun":
                    primary_type = "娛樂/逛街"
                break
        place["primary_type"] = primary_type


    sorted_places = sorted(places_list, key=lambda x: x["weighted_score"], reverse=True)
    return sorted_places


def fetch_place_details(place_id):
    """獲取地點詳細資訊 (Place Details)"""
    resp = requests.get(
        "https://maps.googleapis.com/maps/api/place/details/json",
        params={
            "place_id": place_id,
            "key": API_KEY,
            "language": "zh-TW",
            "fields": "name,rating,formatted_address,formatted_phone_number,website,review,price_level,user_ratings_total,opening_hours",
        },
    ).json()
    result = resp.get("result", {})
    reviews = result.get("reviews", [])[:3] 
    return result, reviews


# ---------- Layout (佈局) ----------
app.layout = html.Div(
    [
# 📌 修正：增加 style 屬性來強行放大圓圈
        dcc.Loading(
            id="loading-search",
            type="circle",
            fullscreen=True,
            color="#0B16EA",
            # 使用 CSS 變換 (transform) 將圓圈放大 2 倍 (scale(2))
            style={"transform": "scale(2)"}, 
            children=dcc.Store(id="loading-trigger-store")),

        html.Div(
            [
                html.H1("附近行程智慧推薦", style={"marginBottom": "5px"}),
                html.P(
                    "輸入出發地與預算，選擇行程類型，系統會依據距離與價位幫你排序推薦。",
                    style={"marginTop": "0px", "color": "#555"},
                ),
            ],
            style={"textAlign": "left", "marginBottom": "20px"},
        ),
        html.Div(
            [
                dcc.Input(
                    id="address",
                    type="text",
                    placeholder="輸入出發地址，例如：台北車站",
                    value=None, 
                    style={
                        "fontSize": 16,
                        "width": "320px",
                        "marginRight": "10px",
                        "padding": "6px 8px",
                    },
                ),
                dcc.Input(
                    id="budget",
                    type="number",
                    placeholder="預算上限（例如 800）",
                    value=None, 
                    style={
                        "fontSize": 16,
                        "width": "180px",
                        "marginRight": "10px",
                        "padding": "6px 8px",
                    },
                ),
                dcc.Dropdown(
                    id="category",
                    options=[
                        {"label": "美食", "value": "food"},
                        {"label": "娛樂 / 逛街", "value": "fun"},
                    ],
                    value=["food", "fun"],
                    multi=True,
                    clearable=False,
                    placeholder="選擇行程類型",
                    style={
                        "width": "260px",
                        "display": "inline-block",
                        "verticalAlign": "middle",
                        "marginRight": "10px",
                    },
                ),
                html.Button(
                    "查詢",
                    id="search-btn",
                    n_clicks=0, # 修改初始值為 0
                    style={
                        "fontSize": 16,
                        "padding": "8px 20px",
                        "backgroundColor": "#1976D2",
                        "color": "white",
                        "border": "none",
                        "borderRadius": "4px",
                        "cursor": "pointer",
                    },
                ),
            ],
            style={
                "display": "flex",
                "flexWrap": "wrap",
                "alignItems": "center",
                "gap": "8px",
                "marginBottom": "10px",
            },
        ),
        html.Div(
            id="budget-warning",
            style={"color": "green", "marginTop": "5px", "marginBottom": "15px", "fontSize": 16},
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.H3("推薦地點", style={"marginBottom": "10px"}),
                        html.Div(
                            id="result-container",
                            children=html.Div(
                                "請先輸入地址與預算後按下「查詢」。",
                                style={"color": "#777", "fontSize": 16},
                            ),
                            style={
                                "border": "1px solid #ddd",
                                "borderRadius": "4px",
                                "padding": "10px",
                                "maxHeight": "450px",
                                "overflowY": "auto",
                                "backgroundColor": "#fafafa",
                            },
                        ),
                        html.Div(
                            [
                                html.Button(
                                    "上一頁",
                                    id="prev-page",
                                    n_clicks=0,
                                    style={"marginRight": "10px"},
                                ),
                                html.Span(id="page-info", style={"marginRight": "10px"}),
                                html.Button("下一頁", id="next-page", n_clicks=0),
                            ],
                            style={"marginTop": "10px"},
                        ),
                    ],
                    style={"flex": "2", "marginRight": "20px"},
                ),
                html.Div(
                    [
                        html.H3("已選行程", style={"marginBottom": "10px"}),
                        html.Div(
                            id="selected-itinerary",
                            style={
                                "border": "1px solid #ddd",
                                "borderRadius": "4px",
                                "padding": "10px",
                                "minHeight": "80px",
                                "maxHeight": "450px",
                                "overflowY": "auto",
                                "backgroundColor": "#fff",
                                "fontSize": 15,
                            },
                        ),
                    ],
                    style={"flex": "1"},
                ),
            ],
            style={"display": "flex", "flexDirection": "row", "marginBottom": "20px"},
        ),
        
        # 📈 圓餅圖容器
        html.Div(
            [
                html.H3("行程分析", style={"marginBottom": "10px"}),
                html.Div(
                    [
                        dcc.Graph(
                            id="budget-pie-chart",
                            style={"width": "50%", "display": "inline-block"},
                            config={"displayModeBar": False},
                        ),
                        dcc.Graph(
                            id="category-pie-chart",
                            style={"width": "50%", "display": "inline-block"},
                            config={"displayModeBar": False},
                        ),
                    ],
                    style={"display": "flex"},
                ),
            ],
            style={"borderTop": "1px solid #eee", "paddingTop": "20px"},
        ),
        
        dcc.Checklist(id="place-selector", options=[], value=[], style={"display": "none"}),
        dcc.Store(id="all-place-details", data={}), 
        dcc.Store(id="all-options", data=[]),       
        dcc.Store(id="page", data=0),             
        dcc.Store(id="detail-cache", data={}),    
        dcc.Store(id="modal-trigger-state", data={"open": False, "pid": None}), 
        
        # 📌 Store: 用於紀錄手動預算分配的 Store
        dcc.Store(id="manual-budget-store", data={}),
        
        html.Div(
            id='detail-backdrop', 
            n_clicks=0, 
            style={
                "position": "fixed", "top": 0, "left": 0, "width": "100vw", "height": "100vh",
                "backgroundColor": "rgba(0,0,0,0.3)", "zIndex": 999, "display": "none"
            }
        ), 
        
        html.Div(
            id='detail-modal', 
            children=html.Div('載入中...'), 
            style={
                "position": "fixed", "top": "50%", "left": "50%", "transform": "translate(-50%, -50%)",
                "backgroundColor": "white", "border": "1px solid #ccc", "borderRadius": "6px",
                "padding": "16px", "boxShadow": "0 2px 8px rgba(0,0,0,0.3)",
                "zIndex": 1000, "width": "420px", "maxHeight": "70vh", "overflowY": "auto",
                "display": "none"
            }
        ),
    ],
    style={
        "maxWidth": "1200px",
        "margin": "20px auto",
        "fontFamily": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "fontSize": 16,
    },
)

# ---------- 查詢主邏輯 (Search) ----------
# 📌 修正點：移除 Output("place-selector", "value") 的主動重置，並合併 old_details 以保留已選地點資訊
@app.callback(
    Output("all-options", "data"),
    Output("all-place-details", "data"),
    Output("place-selector", "options"),
    Output("page", "data"), 
    Output("loading-trigger-store", "data"), 
    Input("search-btn", "n_clicks"),
    State("address", "value"),
    State("budget", "value"),
    State("category", "value"),
    State("all-place-details", "data"), # 📌 讀取目前的 Store
    prevent_initial_call=False, 
)
def search_and_build_options(n, address, budget, category, old_details):
    if not n or n == 0:
        return no_update, no_update, no_update, no_update, no_update
    
    if not address or budget is None or budget <= 0:
        return [], old_details if old_details else {}, [], 0, "done"

    try:
        lat, lng = get_latlng(address, API_KEY)
    except Exception as e:
        return [], old_details if old_details else {}, [], 0, "done"

    if not category:
        category = ["food", "fun"]

    types_list = []
    for c in category:
        types_list.extend(CATEGORY_TYPE_MAP.get(c, []))
    types_list = list(set(types_list))

    nearby = search_places(lat, lng, API_KEY, types_list)
    if not nearby:
        return [], old_details if old_details else {}, [], 0, "done"

    nearby_scored = calculate_weighted_score(
        nearby, lat, lng, budget, distance_weight=0.5, price_weight=0.5
    )
    
    max_price_level = price_level_by_budget(budget)
    options = []
    
    # 📌 關鍵修改：合併新舊地點詳情字典，確保跨地址查詢後，已選地點的名稱不會消失
    new_details = old_details.copy() if old_details else {}
    
    for p in nearby_scored:
        pid = p["place_id"]
        new_details[pid] = p
        
        pl = p.get("price_level")
        try:
            pl_int = int(pl) if pl is not None else None
        except Exception:
            pl_int = None
            
        name = p.get("name", "未知")
        
        if pl_int is not None and pl_int <= max_price_level:
            options.append({"label": name, "value": pid})
            
    return options, new_details, options, 0, "done"


# ---------- 當頁卡片渲染 (Render Page) ----------
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
        return html.Div("請先輸入地址與預算後按下「查詢」。", style={"color": "#777", "fontSize": 16}), ""
    
    page = page or 0
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_options = all_options[start:end]
    selected_values = selected_values or []

    cards = []
    for opt in page_options:
        pid = opt["value"]
        p = all_details.get(pid, {})
        name = p.get("name", "未知")
        addr = p.get("vicinity", "無")
        rating = p.get("rating", "無")
        dist = p.get("distance_km", 0.0)
        score = p.get("weighted_score", 0)
        price_level = p.get("price_level", "無")

        photo_ref = p.get("photo_reference")
        photo_url = None
        if photo_ref:
            photo_url = (
                "https://maps.googleapis.com/maps/api/place/photo"
                f"?maxwidth=180&photo_reference={photo_ref}&key={API_KEY}"
            )

        cards.append(
            html.Div(
                [
                    dcc.Checklist(
                        options=[{"label": "", "value": pid}],
                        value=[pid] if pid in selected_values else [], 
                        id={"type": "place-check", "index": pid},
                        style={"display": "inline-block", "marginRight": "8px"},
                    ),
                    html.Div(
                        children=(
                            html.Img(
                                src=photo_url,
                                style={
                                    "width": "100px",
                                    "height": "100px",
                                    "objectFit": "cover",
                                    "borderRadius": "4px",
                                    "marginRight": "10px",
                                },
                            )
                            if photo_url
                            else None
                        ),
                        style={
                            "display": "inline-block",
                            "verticalAlign": "top",
                        },
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Strong(name, style={"fontSize": 17}),
                                    html.Span(
                                        f" ｜ 推薦分數 {score}/100",
                                        style={"color": "#ffa000", "marginLeft": "4px"},
                                    ),
                                ]
                            ),
                            html.Div(f"地址：{addr}", style={"color": "#555"}),
                            html.Div(
                                f"評分：{rating} ｜ 價位等級：{price_level} ｜ 距離：約 {dist:.2f} 公里",
                                style={"color": "#777", "fontSize": 14},
                            ),
                            html.Button(
                                "查看詳情",
                                id={"type": "detail-btn", "index": pid},
                                n_clicks=0,
                                style={
                                    "marginTop": "4px",
                                    "fontSize": 13,
                                    "padding": "2px 8px",
                                },
                            ),
                        ],
                        style={
                            "display": "inline-block",
                            "verticalAlign": "top",
                            "width": "calc(100% - 130px)" if photo_url else "calc(100% - 30px)",
                        },
                    ),
                    html.Hr(style={"marginTop": "8px", "marginBottom": "8px"}),
                ],
                style={"marginBottom": "4px", "display": "flex", "alignItems": "center"},
            )
        )

    max_page = (len(all_options) - 1) // PAGE_SIZE + 1
    max_page = max(max_page, 1) 
    page_text = f"第 {page + 1} / {max_page} 頁"
    return cards, page_text


# ---------- 換頁邏輯 (Change Page) ----------
@app.callback(
    Output("page", "data", allow_duplicate=True), 
    Input("prev-page", "n_clicks"),
    Input("next-page", "n_clicks"),
    State("page", "data"),
    State("all-options", "data"),
    prevent_initial_call=True,
)
def change_page(prev_clicks, next_clicks, page, all_options):
    ctx = callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate

    if not all_options:
        raise dash.exceptions.PreventUpdate

    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    page = page or 0 

    max_page = (len(all_options) - 1) // PAGE_SIZE 
    
    if trigger == "prev-page":
        page = max(page - 1, 0)
    elif trigger == "next-page":
        page = min(page + 1, max_page)

    return page


# ---------- 同步 Checkbox、移除與排序按鈕 -> place-selector ----------
@app.callback(
    Output("place-selector", "value", allow_duplicate=True), 
    Input({"type": "place-check", "index": ALL}, "value"), 
    Input({"type": "remove-btn", "index": ALL}, "n_clicks"), 
    Input({"type": "move-up", "index": ALL}, "n_clicks"),
    Input({"type": "move-down", "index": ALL}, "n_clicks"),
    State("place-selector", "value"),
    prevent_initial_call=True,
)
def sync_checks_and_order(check_values, remove_clicks, up_clicks, down_clicks, current_selected):
    ctx = callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate

    trigger_prop = ctx.triggered[0]["prop_id"]
    trigger_id_raw = trigger_prop.split(".")[0]
    trigger_value = ctx.triggered[0]["value"]

    current_list = list(current_selected or [])
    
    try:
        trigger_dict = json.loads(trigger_id_raw)
        pid = trigger_dict.get("index")
        type_ = trigger_dict.get("type")
    except:
        raise dash.exceptions.PreventUpdate

    if type_ == "place-check":
        if trigger_value and pid not in current_list:
            current_list.append(pid)
        elif not trigger_value and pid in current_list:
            current_list.remove(pid)
            
    elif type_ == "remove-btn":
        if pid in current_list:
            current_list.remove(pid)

    elif type_ == "move-up":
        idx = current_list.index(pid)
        if idx > 0:
            current_list[idx], current_list[idx-1] = current_list[idx-1], current_list[idx]

    elif type_ == "move-down":
        idx = current_list.index(pid)
        if idx < len(current_list) - 1:
            current_list[idx], current_list[idx+1] = current_list[idx+1], current_list[idx]

    return current_list


# 📌 修正：處理手動預算的 Callback
@app.callback(
    Output("manual-budget-store", "data"),
    Input({"type": "budget-input", "index": ALL}, "value"),
    State({"type": "budget-input", "index": ALL}, "id"),
    State("manual-budget-store", "data"),
    prevent_initial_call=True
)
def update_manual_budgets(values, ids, current_budgets):
    current_budgets = current_budgets or {}
    for val, id_dict in zip(values, ids):
        pid = id_dict["index"]
        current_budgets[pid] = val if val is not None else 0
    return current_budgets


# ---------- 預算檢查 (Budget Check) ----------
@app.callback(
    Output("budget-warning", "children", allow_duplicate=True), 
    Input("place-selector", "value"),
    Input("manual-budget-store", "data"),
    State("budget", "value"),
    prevent_initial_call=True,
)
def check_budget(selected_places, manual_budgets, budget):
    if not selected_places or not budget:
        return ""
    
    manual_budgets = manual_budgets or {}
    total_cost = 0
    for place_id in selected_places:
        total_cost += manual_budgets.get(place_id, 0)
        
    if total_cost > budget:
        return html.Span(f"⚠️ 目前分配預算約 {total_cost:.0f}，已超出預算 {budget}。", style={"color": "red"})
        
    return html.Span(f"目前分配預算約 {total_cost:.0f}，在預算 {budget} 以內。", style={"color": "green"})


# ---------- 右側已選行程渲染 (Selected Itinerary) ----------
@app.callback(
    Output("selected-itinerary", "children"),
    Input("place-selector", "value"),
    State("manual-budget-store", "data"),
    State("all-place-details", "data"),
)
def show_selected_itinerary(selected_places, manual_budgets, all_details):
    if not selected_places:
        return html.Div("尚未選擇任何地點。", style={"color": "#777"})
    
    manual_budgets = manual_budgets or {}
    items = []
    for i, pid in enumerate(selected_places):
        p = all_details.get(pid, {})
        name = p.get("name", "未知")
        addr = p.get("vicinity", "無")
        rating = p.get("rating", "無")
        dist = p.get("distance_km", 0.0)
        
        stored_cost = manual_budgets.get(pid)
        initial_val = stored_cost if stored_cost is not None else get_estimated_cost(p.get("price_level"))

        items.append(
            html.Li(
                [
                    html.Div(
                        [
                            html.Span(f"{i+1}. ", style={"fontWeight": "bold", "marginRight": "5px"}),
                            html.Span(name, style={"fontWeight": "bold"}),
                            html.Span([
                                html.Button("↑", id={"type": "move-up", "index": pid}, style={"marginLeft": "5px", "padding": "0 5px"}),
                                html.Button("↓", id={"type": "move-down", "index": pid}, style={"marginLeft": "2px", "padding": "0 5px"}),
                            ], style={"float": "right"})
                        ],
                        style={"marginBottom": "2px"}
                    ),
                    html.Div([
                        html.Span("分配預算: ", style={"fontSize": "13px"}),
                        dcc.Input(
                            id={"type": "budget-input", "index": pid},
                            type="number",
                            value=initial_val,
                            debounce=True,
                            style={"width": "80px", "marginLeft": "5px"}
                        ),
                        html.Span(" 元", style={"fontSize": "13px"})
                    ], style={"marginBottom": "5px"}),
                    html.Div(f"地址：{addr}", style={"fontSize": 13, "color": "#555"}),
                    html.Button(
                        "移除",
                        id={"type": "remove-btn", "index": pid},
                        n_clicks=0,
                        style={
                            "marginTop": "2px",
                            "fontSize": 12,
                            "padding": "2px 6px",
                            "color": "red"
                        },
                    ),
                ],
                style={"marginBottom": "10px", "paddingBottom": "4px", "borderBottom": "1px solid #eee"}
            )
        )
    return html.Ol(items, style={"paddingLeft": "0px", "listStyleType": "none"}) 


# ----------------------------------------------------
# 📈 圓餅圖數據計算和渲染
# ----------------------------------------------------
@app.callback(
    Output("budget-pie-chart", "figure"),
    Output("category-pie-chart", "figure"),
    Input("place-selector", "value"),
    Input("manual-budget-store", "data"),
    State("budget", "value"),
    State("all-place-details", "data"),
)
def render_pie_charts(selected_places, manual_budgets, total_budget, all_details):
    empty_figure = {
        'data': [{'type': 'pie', 'labels': ['無資料'], 'values': [1], 'marker': {'colors': ['#f0f0f0']}}],
        'layout': {'title': {'text': '無選定行程', 'font': {'size': 16}}, 'margin': {'t': 40, 'b': 20, 'l': 0, 'r': 0}, 'showlegend': False}
    }

    if not selected_places:
        return empty_figure, empty_figure

    manual_budgets = manual_budgets or {}
    budget_labels = []
    budget_values = []
    total_spent = 0
    category_counts = {}
    
    for pid in selected_places:
        p = all_details.get(pid, {})
        name = p.get("name", "未知")
        cost = manual_budgets.get(pid, 0)
        budget_labels.append(name)
        budget_values.append(cost)
        total_spent += cost
            
        primary_type = p.get("primary_type", "其他")
        category_counts[primary_type] = category_counts.get(primary_type, 0) + 1

    remaining_budget = max(total_budget - total_spent, 0) if total_budget else 0
    budget_data = []
    
    if any(v > 0 for v in budget_values):
        if total_budget and remaining_budget > 0:
            budget_labels.append(f"剩餘預算 ({remaining_budget:.0f})")
            budget_values.append(remaining_budget)
        
        budget_data = [
            {
                'type': 'pie',
                'labels': budget_labels,
                'values': budget_values,
                'hole': .3,
                'hoverinfo': 'label+percent+value',
                'textinfo': 'label',
                'marker': {'colors': ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']},
            }
        ]
        budget_title = f"行程預算佔比 (總分配: {total_spent})"
    else:
        budget_data = empty_figure['data']
        budget_title = "預算分配中..."
        
    budget_figure = {
        'data': budget_data,
        'layout': {
            'title': {'text': budget_title, 'font': {'size': 16}}, 
            'margin': {'t': 40, 'b': 20, 'l': 0, 'r': 0},
            'showlegend': True
        }
    }

    category_labels = list(category_counts.keys())
    category_values = list(category_counts.values())

    category_figure = {
        'data': [
            {
                'type': 'pie',
                'labels': category_labels,
                'values': category_values,
                'hole': .3,
                'hoverinfo': 'label+value',
                'textinfo': 'label+percent',
                'marker': {'colors': ['#ff7f0e', '#1f77b4', '#9467bd', '#d62728']},
            }
        ] if category_values else empty_figure['data'],
        'layout': {
            'title': {'text': "已選行程類型分佈", 'font': {'size': 16}},
            'margin': {'t': 40, 'b': 20, 'l': 0, 'r': 0},
            'showlegend': True
        }
    }
    
    return budget_figure, category_figure
    
# 📌 CALLBACK 1: 控制彈窗開啟/關閉狀態
@app.callback(
    Output("modal-trigger-state", "data"),
    Input({"type": "detail-btn", "index": ALL}, "n_clicks"),
    Input("detail-backdrop", "n_clicks"),
    Input({"type": "close-detail", "index": ALL}, "n_clicks"),
    State("modal-trigger-state", "data"),
    prevent_initial_call=True,
)
def update_modal_trigger_state(detail_clicks, backdrop_clicks, close_clicks, current_state):
    from dash import callback_context, no_update

    ctx = callback_context
    if not ctx.triggered:
        return no_update

    trigger_prop = ctx.triggered[0]["prop_id"]
    trigger_id = trigger_prop.split(".")[0]
    
    if trigger_id == "detail-backdrop" or "close-detail" in trigger_id:
        if current_state.get("open"):
            return {"open": False, "pid": None}
        return no_update

    place_id = None
    if "detail-btn" in trigger_id:
        try:
            if ctx.triggered[0]["value"] > 0:
                trigger_dict = json.loads(trigger_id.replace("'", '"'))
                place_id = trigger_dict.get("index")
        except Exception:
            return no_update

    if place_id:
        if not current_state.get("open") or current_state.get("pid") != place_id:
            return {"open": True, "pid": place_id}
        
    return no_update

# 📌 CALLBACK 2: 渲染彈窗內容
@app.callback(
    Output("detail-modal", "children"),
    Output("detail-modal", "style"),
    Output("detail-backdrop", "style"),
    Output("detail-cache", "data"), 
    Input("modal-trigger-state", "data"), 
    State("detail-cache", "data"),
    prevent_initial_call=True,
)
def render_detail_modal(trigger_state, cache):
    from dash import no_update

    is_open = trigger_state.get("open", False)
    place_id = trigger_state.get("pid")
    
    if not is_open or not place_id:
        modal_style = {
            "position": "fixed", "top": "50%", "left": "50%", "transform": "translate(-50%, -50%)",
            "backgroundColor": "white", "border": "1px solid #ccc", "borderRadius": "6px",
            "padding": "16px", "boxShadow": "0 2px 8px rgba(0,0,0,0.3)",
            "zIndex": 1000, "width": "420px", "maxHeight": "70vh", "overflowY": "auto",
            "display": "none", 
        }
        backdrop_style = {
            "position": "fixed", "top": 0, "left": 0, "width": "100vw", "height": "100vh",
            "backgroundColor": "rgba(0,0,0,0.3)", "zIndex": 999, "display": "none", 
        }
        return html.Div(), modal_style, backdrop_style, no_update

    cache = cache or {}
    if place_id in cache:
        detail = cache[place_id]
        result = detail["result"]
        reviews = detail["reviews"]
        new_cache = no_update
    else:
        try:
            result, reviews = fetch_place_details(place_id) 
            cache[place_id] = {"result": result, "reviews": reviews} 
            new_cache = cache
        except Exception:
            return html.Div("詳情加載失敗"), no_update, no_update, no_update

    name = result.get("name", "未知")
    addr = result.get("formatted_address", "無地址")
    rating = result.get("rating", "無")
    user_ratings_total = result.get("user_ratings_total", 0)
    phone = result.get("formatted_phone_number")
    website = result.get("website")
    open_status = result.get("opening_hours", {}).get("open_now")
    
    if open_status is True:
        open_text = html.Span("✅ 營業中", style={"color": "green", "fontWeight": "bold"})
    elif open_status is False:
        open_text = html.Span("❌ 已歇業或未營業", style={"color": "red", "fontWeight": "bold"})
    else:
        open_text = html.Span("N/A", style={"color": "#777"})
        
    review_blocks = []
    for rv in reviews:
        author = rv.get("author_name", "匿名")
        text = rv.get("text", "")
        score = rv.get("rating", "")
        relative_time = rv.get("relative_time_description", "")
        review_blocks.append(
            html.Div([
                html.Div([
                    html.Span(author, style={"fontWeight": "bold"}),
                    html.Span(f" ｜ 評分 {score} ({relative_time})", style={"fontSize": 13, "color": "#ffa000"}),
                ]),
                html.Div(text, style={"fontSize": 13, "color": "#444", "marginBottom": "6px"}),
            ], style={"marginBottom": "8px", "paddingLeft": "10px", "borderLeft": "2px solid #ddd"})
        )
        
    content = html.Div([
        html.Div([
            html.Span(name, style={"fontSize": 18, "fontWeight": "bold"}),
            html.Button("關閉", id={"type": "close-detail", "index": place_id}, n_clicks=0, style={"float": "right", "fontSize": 12, "padding": "2px 8px", "border": "1px solid #ccc", "borderRadius": "4px", "cursor": "pointer"}),
        ], style={"marginBottom": "8px", "borderBottom": "1px solid #eee", "paddingBottom": "8px"}),
        html.Div(f"地址：{addr}", style={"fontSize": 14, "marginBottom": "4px"}),
        html.Div([
            html.Span(f"平均評分：{rating} ({user_ratings_total} 則評論)"),
            html.Span(" ｜ 營業狀態："), open_text,
        ], style={"fontSize": 14, "marginBottom": "4px"}),
        html.Div(f"電話：{phone}" if phone else "電話：無", style={"fontSize": 14}),
        html.Div([
            "網站：",
            html.A(website, href=website, target="_blank", style={"color": "#1976D2"}) if website else "無",
        ], style={"fontSize": 14, "marginBottom": "12px"}),
        html.Hr(),
        html.Div("最新評論（最多 3 則）：", style={"fontWeight": "bold", "marginBottom": "6px"}),
        *(review_blocks if review_blocks else [html.Div("無評論資訊", style={"color": "#777"})]),
    ])
    
    modal_style = {
        "position": "fixed", "top": "50%", "left": "50%", "transform": "translate(-50%, -50%)",
        "backgroundColor": "white", "border": "1px solid #ccc", "borderRadius": "6px",
        "padding": "16px", "boxShadow": "0 2px 8px rgba(0,0,0,0.3)",
        "zIndex": 1000, "width": "420px", "maxHeight": "70vh", "overflowY": "auto",
        "display": "block",
    }
    backdrop_style = {
        "position": "fixed", "top": 0, "left": 0, "width": "100vw", "height": "100vh",
        "backgroundColor": "rgba(0,0,0,0.3)", "zIndex": 999, "display": "block",
    }
    
    return content, modal_style, backdrop_style, new_cache


if __name__ == "__main__":
    app.run(debug=True)