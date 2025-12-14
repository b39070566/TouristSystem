import dash
from dash import dcc, html, Output, Input, State
from dash.dependencies import ALL
import requests

app = dash.Dash(__name__)

API_KEY = ""

# 行程類別對應的 place types
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

PAGE_SIZE = 10  # 每頁 10 筆

# -----------------------
# 版面設計 layout
# -----------------------
app.layout = html.Div(
    [
        # 頁面標題
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
        # 搜尋列
        html.Div(
            [
                dcc.Input(
                    id="address",
                    type="text",
                    placeholder="輸入出發地址，例如：台北車站",
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
                    value=["food", "fun"],  # 預設兩種都選
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
        # 預算警示
        html.Div(
            id="budget-warning",
            style={"color": "red", "marginTop": "5px", "marginBottom": "15px", "fontSize": 16},
        ),
        # 主體：左側推薦清單 + 右側已選行程
        html.Div(
            [
                # 左側：推薦清單
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
                        # 分頁控制列
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
                # 右側：已選行程摘要
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
            style={"display": "flex", "flexDirection": "row"},
        ),
        # 隱藏：總體 Checklist + place 詳細資料 + 全部 options + 當前頁數
        dcc.Checklist(id="place-selector", options=[], value=[], style={"display": "none"}),
        dcc.Store(id="all-place-details", data={}),
        dcc.Store(id="all-options", data=[]),
        dcc.Store(id="page", data=0),
    ],
    style={
        "maxWidth": "1200px",
        "margin": "20px auto",
        "fontFamily": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "fontSize": 16,
    },
)

# -----------------------
# 工具函式
# -----------------------
def get_latlng(address, apikey):
    resp = requests.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": address, "key": apikey},
    ).json()
    loc = resp["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


def search_places(lat, lng, apikey, types_list, radius=1000):
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
                all_results.append(r)
    return all_results


def price_level_by_budget(budget):
    if budget is None:
        return 4
    if budget <= 200:
        return 1
    elif budget <= 600:
        return 2
    elif budget <= 1400:
        return 3
    else:
        return 4


def within_budget(price_range, budget):
    if not price_range or budget is None:
        return False
    try:
        price_range = price_range.replace("$", "")
        start_str, end_str = price_range.split("-")
        start, end = float(start_str.strip()), float(end_str.strip())
        return start <= budget
    except Exception:
        return False


def calculate_distance(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, sqrt, atan2

    R = 6371
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def normalize_score(value, min_val, max_val):
    if max_val == min_val:
        return 0
    return 1 - (value - min_val) / (max_val - min_val)


def calculate_weighted_score(
    places_list, user_lat, user_lng, budget, distance_weight=0.5, price_weight=0.5
):
    if not places_list:
        return []
    for place in places_list:
        lat = place.get("geometry", {}).get("location", {}).get("lat")
        lng = place.get("geometry", {}).get("location", {}).get("lng")
        if lat and lng:
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
        valid_distances = [0, 1]
    if not valid_prices:
        valid_prices = [1, 4]

    min_distance = min(valid_distances)
    max_distance = max(valid_distances)
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

    sorted_places = sorted(places_list, key=lambda x: x["weighted_score"], reverse=True)
    return sorted_places


# -----------------------
# 回呼：查詢 & 建立完整 options（不分頁）
# -----------------------
@app.callback(
    Output("all-options", "data"),
    Output("all-place-details", "data"),
    Input("search-btn", "n_clicks"),
    State("address", "value"),
    State("budget", "value"),
    State("category", "value"),
)
def search_and_build_options(n, address, budget, category):
    if not n:
        return [], {}
    if not address or not budget:
        return [], {}
    try:
        lat, lng = get_latlng(address, API_KEY)
    except Exception:
        return [], {}
    if not category:
        category = ["food", "fun"]

    types_list = []
    for c in category:
        types_list.extend(CATEGORY_TYPE_MAP.get(c, []))
    types_list = list(set(types_list))

    nearby = search_places(lat, lng, API_KEY, types_list)
    if not nearby:
        return [], {}

    max_price_level = price_level_by_budget(budget)
    nearby_scored = calculate_weighted_score(
        nearby, lat, lng, budget, distance_weight=0.5, price_weight=0.5
    )

    options = []
    place_details_dict = {}
    for p in nearby_scored:
        place_details_dict[p["place_id"]] = p
        pl = p.get("price_level")
        try:
            pl_int = int(pl) if pl is not None else None
        except Exception:
            pl_int = None
        name = p.get("name", "未知")
        if pl_int is not None and pl_int <= max_price_level:
            options.append({"label": name, "value": p["place_id"]})
        elif "price_range" in p and within_budget(p["price_range"], budget):
            options.append({"label": name, "value": p["place_id"]})

    return options, place_details_dict


# -----------------------
# 回呼：依 all-options + page 繪製當頁卡片
# -----------------------
@app.callback(
    Output("result-container", "children"),
    Output("place-selector", "options"),
    Output("page-info", "children"),
    Input("all-options", "data"),
    Input("page", "data"),
    State("all-place-details", "data"),
)
def render_page(all_options, page, all_details):
    if not all_options:
        return "請先輸入地址與預算後按下「查詢」。", [], ""
    page = page or 0
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_options = all_options[start:end]
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
        cards.append(
            html.Div(
                [
                    dcc.Checklist(
                        options=[{"label": "", "value": pid}],
                        value=[],
                        id={"type": "place-check", "index": pid},
                        style={"display": "inline-block", "marginRight": "8px"},
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
                        ],
                        style={"display": "inline-block", "verticalAlign": "top", "width": "90%"},
                    ),
                    html.Hr(style={"marginTop": "8px", "marginBottom": "8px"}),
                ],
                style={"marginBottom": "4px"},
            )
        )
    max_page = (len(all_options) - 1) // PAGE_SIZE + 1
    page_text = f"第 {page + 1} / {max_page} 頁"
    return cards, all_options, page_text


# -----------------------
# 回呼：按上一頁 / 下一頁改變 page（同時處理查詢重設 page）
# -----------------------
@app.callback(
    Output("page", "data"),
    Input("prev-page", "n_clicks"),
    Input("next-page", "n_clicks"),
    Input("search-btn", "n_clicks"),
    State("page", "data"),
    State("all-options", "data"),
    prevent_initial_call=True,
)
def change_page(prev_clicks, next_clicks, search_clicks, page, all_options):
    from dash import callback_context

    ctx = callback_context
    if not ctx.triggered:
        return page or 0

    trigger = ctx.triggered[0]["prop_id"].split(".")[0]

    # 若是按下「查詢」，直接把 page 重設為 0
    if trigger == "search-btn":
        return 0

    if not all_options:
        return 0

    page = page or 0
    if trigger == "prev-page":
        page = max(page - 1, 0)
    elif trigger == "next-page":
        max_page = (len(all_options) - 1) // PAGE_SIZE
        page = min(page + 1, max_page)
    return page


# -----------------------
# 回呼：把每張卡片的 checkbox 同步到 place-selector
# -----------------------
@app.callback(
    Output("place-selector", "value"),
    Input({"type": "place-check", "index": ALL}, "value"),
    State("place-selector", "options"),
)
def sync_checks(values, options):
    selected_ids = []
    for v_list in values:
        if v_list:
            selected_ids.extend(v_list)
    valid_ids = {opt["value"] for opt in options}
    selected_ids = [pid for pid in selected_ids if pid in valid_ids]
    return selected_ids


# -----------------------
# 回呼：預算檢查
# -----------------------
@app.callback(
    Output("budget-warning", "children"),
    Input("place-selector", "value"),
    State("budget", "value"),
    State("all-place-details", "data"),
)
def check_budget(selected_places, budget, all_details):
    if not selected_places or not budget:
        return ""
    total_cost = 0
    for place_id in selected_places:
        detail = all_details.get(place_id, {})
        cost = 0
        pr = detail.get("price_range")
        if pr and "-" in pr:
            try:
                pr_clean = pr.replace("$", "")
                start, end = pr_clean.split("-")
                cost = (float(start.strip()) + float(end.strip())) / 2
            except Exception:
                cost = 0
        else:
            pl = detail.get("price_level")
            try:
                pl_int = int(pl) if pl is not None else None
            except Exception:
                pl_int = None
            if pl_int:
                level_price_map = {1: 100, 2: 400, 3: 800, 4: 1200}
                cost = level_price_map.get(pl_int, 0)
        total_cost += cost
    if total_cost > budget:
        return f"⚠️ 目前選擇的行程估計花費約 {total_cost:.0f}，已超出預算 {budget}，請調整選擇或提高預算。"
    return f"目前選擇的行程估計花費約 {total_cost:.0f}，在預算 {budget} 以內。"


# -----------------------
# 回呼：右側已選行程摘要
# -----------------------
@app.callback(
    Output("selected-itinerary", "children"),
    Input("place-selector", "value"),
    State("all-place-details", "data"),
)
def show_selected_itinerary(selected_places, all_details):
    if not selected_places:
        return html.Div("尚未選擇任何地點。", style={"color": "#777"})
    items = []
    for pid in selected_places:
        p = all_details.get(pid, {})
        name = p.get("name", "未知")
        addr = p.get("vicinity", "無")
        rating = p.get("rating", "無")
        dist = p.get("distance_km", 0.0)
        items.append(
            html.Li(
                [
                    html.Span(name, style={"fontWeight": "bold"}),
                    html.Span(f" ｜ 評分 {rating} ｜ 距離 {dist:.2f} 公里"),
                    html.Div(f"地址：{addr}", style={"fontSize": 13, "color": "#555"}),
                ],
                style={"marginBottom": "6px"},
            )
        )
    return html.Ul(items, style={"paddingLeft": "18px"})


if __name__ == "__main__":
    app.run(debug=True)
