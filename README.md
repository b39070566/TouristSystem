
---

# 📋 附近行程智慧推薦系統 (Nearby Trip Recommender)

本專案是一個基於 **Dash（Flask）** 架構的全端 Web 應用，旨在協助使用者依據**地理位置與預算限制**，即時規劃並管理個人化旅遊行程。

系統整合地圖服務、預算分析與互動式介面，提供從「景點探索 → 行程規劃 → 預算控制」的一站式體驗。

---

## 🌟 核心亮點

###  地理位置感知推薦

* 串接 **Google Places API（Nearby Search & Place Details）**
* 即時取得周邊景點、餐廳與店家資訊
* 根據使用者出發地提供在地化推薦

---

###  智慧預算分配系統

* 自動解析 `price_level（$–$$$$）`
* 映射為實際金額區間（如 $$ ≈ NT$600）
* 提供：

  * 📊 即時預算進度條（綠：安全 / 紅：超支）
  * 🥧 預算分配圓餅圖
  * ⚠️ 超支提示機制

---

###  行程持久化與狀態管理

* 使用 SQLite 儲存使用者資料與行程
* 支援「自動恢復」未完成行程
* 歷史紀錄管理與快速載入

---

###  高互動 UI / UX 設計

* 使用 Dash Pattern-Matching Callbacks
* 支援：

  * 動態新增 / 刪除行程項目
  * 即時排序
  * 詳細資訊彈窗（Modal）
* 提供流暢的單頁式操作體驗（SPA-like）

---

##  系統架構

```text
[Frontend - Dash UI]
        ↓ Callback
[Flask Server / Business Logic]
        ↓
[SQLite Database]
        ↓
[Google Maps Platform APIs]
```

---

##  技術棧 (Tech Stack)

### 🔹 前端 (Frontend)

* Plotly Dash（HTML Components, Core Components）
* Dash Bootstrap Components
* 自訂 CSS

### 🔹 後端 (Backend)

* Flask（Web Server）
* Flask-Login（使用者驗證與 Session 管理）

### 🔹 資料庫 (Database)

* SQLite3（Raw SQL）
* PRAGMA 優化設定

### 🔹 外部服務 (APIs)

* Google Maps Platform：

  * Geocoding API
  * Nearby Search API
  * Place Details API
  * Place Photo API

### 🔹 開發工具 (Dev Tools)

* python-dotenv（環境變數管理）
* Werkzeug（密碼加密 / 安全處理）

---

## 🚀 關鍵技術實作

### 1️⃣ 資料庫效能與併發優化

針對 SQLite 在 Web 環境中的鎖定問題，進行以下優化：

*  **PRAGMA 調校**

  * `journal_mode=DELETE`
  * `synchronous=FULL`
  * 確保資料寫入一致性與穩定性

*  **連線生命週期管理**

  * 封裝 DB 操作函式
  * 每次 Query 後確實關閉 Connection
  * 避免 Database Lock 問題

*  **資料表設計**

  * `Users`
  * `Itineraries`
  * `History`
  * 使用 Unique Index 提升查詢效率與資料一致性

---

### 2️⃣ 動態預算計算引擎

*  **價格映射機制**

  * `$ → 低價`
  * `$$ → 中價`
  * `$$$ → 高價`
  * `$$$$ → 高端消費`

*  **即時回饋機制**

  * 透過 Dash Callbacks 監聽所有輸入變化
  * 即時更新：

    * 預算使用率
    * 圖表比例
    * UI 顏色狀態

---

### 3️⃣ 使用者驗證與狀態管理

*  整合 Flask-Login
*  密碼使用 `PBKDF2` 雜湊儲存
*  Session-based 使用者狀態管理
*  登入後自動恢復未完成行程

---

## 🔧 安裝與執行

### 1️⃣ Clone 專案

```bash
git clone https://github.com/yourusername/your-repo.git
```

### 2️⃣ 安裝依賴

```bash
pip install -r requirements.txt
```

### 3️⃣ 設定環境變數

建立 `.env` 檔案：

```env
API_KEY=你的GoogleAPI金鑰
SECRET_KEY=你的Flask密鑰
```

### 4️⃣ 啟動應用

```bash
python app.py
```

---


