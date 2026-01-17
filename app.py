import streamlit as st
import yfinance as yf
import pandas as pd
import json
import random
import string
import re
import requests
from datetime import datetime, timezone

# === 設定 ===
PREDICT_DAYS_DAILY = 20
PREDICT_BARS_5M = 20

st.set_page_config(page_title="株トレードゲーム", layout="wide")

# === メッセージリスト定義 ===
MESSAGES = {
    "god": [
        "未来から来たんですか？", "SECが監視を始めました。", "天才現る。", "バフェットが電話番号を知りたがっています。", "その透視能力、カジノでは使わないで。", "全知全能ですか？"
    ],
    "pro": [
        "素晴らしい！", "目をつぶって発注しても勝てそう。", "働いたら負けですね。", "ウォール街がヘッドハントに来ます。", "完璧な読み。", "芸術的なトレード。"
    ],
    "normal": [
        "コイントスと同じ。", "サルのダーツ投げレベル。", "凡人。", "AIに仕事奪われますよ。", "記憶に残らないトレード。", "プラマイゼロ。"
    ],
    "bad": [
        "養分乙。", "引退をおすすめします。", "画面逆さま？", "勉強代にしては高い。", "定期預金にしましょう。", "アルゴのカモ。"
    ],
    "disaster": [
        "逆にすごい！", "全人類への逆指標。", "PC電源入ってます？", "逆張りすれば億万長者。", "呼吸するように損してますね。", "お祓いに行きましょう。"
    ]
}

def get_japanese_name(ticker):
    code_only = ticker.replace('.T', '')
    url = f"https://finance.yahoo.co.jp/quote/{code_only}.T"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3)
        res.encoding = res.apparent_encoding
        if res.status_code == 200:
            match = re.search(r'<title>(.*?)【', res.text)
            if match: return match.group(1).strip()
    except: pass
    try:
        t = yf.Ticker(ticker)
        return t.info.get('longName', ticker)
    except: return ticker

@st.cache_data(ttl=3600)
def fetch_raw_data(ticker, period, interval):
    try:
        # 3分足はyfinanceにないため、1分足を取得してリサンプリングする
        if interval == "3m":
            # 1分足を取得 (期間は7日が限界)
            df = yf.download(ticker, period=period, interval="1m", progress=False, auto_adjust=False)
            if df.empty:
                return None, "データが見つかりませんでした (3m resampling from 1m)"
            
            # マルチインデックス対応
            if isinstance(df.columns, pd.MultiIndex):
                try: df.columns = df.columns.get_level_values(0)
                except: pass

            # タイムゾーン処理前にリサンプリング用に処理
            if df.index.tz is not None:
                df.index = df.index.tz_convert('Asia/Tokyo')
            
            # 3分足にリサンプリング
            # Openは最初の値、Highは最大値、Lowは最小値、Closeは最後の値、Volumeは合計
            resampled = df.resample('3T').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            })
            df = resampled.dropna()
            
            # 統一的に Naive にする
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            
            return df, None

        # 通常取得
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
        if df.empty: return None, "データなし"
        
        if isinstance(df.columns, pd.MultiIndex):
            try: df.columns = df.columns.get_level_values(0)
            except: pass
            
        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(c in df.columns for c in required): return None, "データ不足"

    except Exception as e: return None, f"エラー: {e}"

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # タイムゾーン処理: 日本時間に変換してTimeZone情報を削除（Naiveにする）
    if df.index.tz is not None:
        df.index = df.index.tz_convert('Asia/Tokyo').tz_localize(None)

    return df, None

def process_data(df, mode, selected_date_str=None):
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA25'] = df['Close'].rolling(25).mean()
    df['MA75'] = df['Close'].rolling(75).mean()
    df = df.dropna()

    ctx_df = pd.DataFrame()
    tgt_df = pd.DataFrame()

    if mode == 'daily':
        if len(df) < PREDICT_DAYS_DAILY + 50: return None, "データ不足"
        
        target_idx = -PREDICT_DAYS_DAILY # Default to latest
        
        if selected_date_str:
            # 日付文字列から該当するIndexを探す (日付以前の直近の日)
            try:
                # 指定日以降のデータで一番古いものの位置を探すのが正確だが、
                # indexは昇順なので、指定日以上(>=)の最初の要素
                sel_ts = pd.Timestamp(selected_date_str).replace(tzinfo=None)
                after_mask = df.index >= sel_ts
                if after_mask.any():
                    # その日の位置を取得
                    # しかし、dfは全体なので、targetの開始位置はそこになる
                    # つまり tgt_df = df.iloc[start_pos : start_pos+20]
                    start_pos = list(after_mask).index(True)
                    
                    # 十分なcontextがあるか確認
                    if start_pos < 50:
                        return None, "開始日が古すぎます（過去データ不足）"
                    if start_pos + PREDICT_DAYS_DAILY > len(df):
                        # 未来すぎる場合は末尾に合わせる
                        start_pos = len(df) - PREDICT_DAYS_DAILY
                    
                    ctx_df = df.iloc[:start_pos].tail(200) # 直近200本
                    tgt_df = df.iloc[start_pos:] # JS側でページングするので残りは全部渡す
                else:
                    return None, "指定日のデータがありません"
            except Exception as e:
                return None, f"日付処理エラー: {e}"
        else:
            ctx_df = df.iloc[:-PREDICT_DAYS_DAILY]
            tgt_df = df.iloc[-PREDICT_DAYS_DAILY:]

    elif mode in ['5m', '3m', '1m']:
        if not selected_date_str: return None, "日付未選択"
        target_mask = df.index.strftime('%Y-%m-%d') == selected_date_str
        tgt_df = df.loc[target_mask]
        if tgt_df.empty: return None, "選択日のデータなし"
        
        # JS側でページングするため、ここでは全データを返す（リミットはJSで管理）
        
        cutoff_time = tgt_df.index[0]
        ctx_df = df[df.index < cutoff_time].tail(200)

    is_intraday = (mode in ['5m', '3m', '1m'])

    def make_entry(t_idx, r, is_intraday):
        if is_intraday:
            # JSTの時刻をそのままあえてUTCとしてTimestamp化することで
            # Lightweight Charts (デフォルトUTC表示) で見たときに
            # 日本時間通りの時刻 (09:00など) が表示されるようにするトリック
            # t_idx は Naive (JST時刻が入っている)
            t_val = int(t_idx.replace(tzinfo=timezone.utc).timestamp())
        else:
            t_val = t_idx.strftime('%Y-%m-%d')

        return {
            "time": t_val,
            "open": r['Open'], "high": r['High'], "low": r['Low'], "close": r['Close'],
            "vol": r['Volume'],
            "ma5": r['MA5'], "ma25": r['MA25'], "ma75": r['MA75']
        }

    ctx_data = {"c": [], "v": [], "m5": [], "m25": [], "m75": []}
    tgt_data = {"c": [], "v": [], "m5": [], "m25": [], "m75": []}

    for t, r in ctx_df.iterrows():
        e = make_entry(t, r, is_intraday)
        ctx_data["c"].append({"time": e["time"], "open": e["open"], "high": e["high"], "low": e["low"], "close": e["close"]})
        ctx_data["v"].append({"time": e["time"], "value": e["vol"], "color": 'rgba(200, 200, 200, 0.4)'})
        for m in ['m5', 'm25', 'm75']: ctx_data[m].append({"time": e["time"], "value": e["ma"+m[1:]]})

    for t, r in tgt_df.iterrows():
        e = make_entry(t, r, is_intraday)
        tgt_data["c"].append({"time": e["time"], "open": e["open"], "high": e["high"], "low": e["low"], "close": e["close"]})
        tgt_data["v"].append({"time": e["time"], "value": e["vol"], "color": 'rgba(200, 200, 200, 0.4)'})
        for m in ['m5', 'm25', 'm75']: tgt_data[m].append({"time": e["time"], "value": e["ma"+m[1:]]})

    return {"ctx": ctx_data, "tgt": tgt_data}, None

def render_game_html(data, sub_data_map, ticker_name, ticker_code, mode, sub_mode_keys, sub_intervals):
    json_data = json.dumps(data)
    json_sub_map = json.dumps(sub_data_map)
    json_msgs = json.dumps(MESSAGES)
    json_sub_intervals = json.dumps(sub_intervals)
    
    # メインチャートの時間設定
    time_scale_opts = "{ timeVisible: true, secondsVisible: false }"
    if mode in ['5m', '3m', '1m']:
        time_scale_opts = """{
            timeVisible: true, 
            secondsVisible: false,
            tickMarkFormatter: (time, tickMarkType, locale) => {
                const d = new Date(time * 1000);
                return d.getUTCHours().toString().padStart(2,'0') + ':' + d.getUTCMinutes().toString().padStart(2,'0');
            }
        }"""

    # サブチャート切り替え用オプションHTML
    # sub_mode_keys = ["日足", "週足"] or ["週足", "月足"]
    # 初期選択は keys[0] とする
    options_html = ""
    for k in sub_mode_keys:
        options_html += f'<option value="{k}">{k}</option>'

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://unpkg.com/lightweight-charts@3.8.0/dist/lightweight-charts.standalone.production.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
        <style>
            body {{ margin: 0; padding: 0; background: #0e1117; font-family: 'Inter', sans-serif; }}
            .game-container {{
                background: #1a1a1a; color: #f3f4f6; padding: 20px; border-radius: 16px;
                width: 100%; max-width: 900px; margin: 0 auto; box-sizing: border-box;
                box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            }}
            .header {{
                display: flex; justify-content: space-between; align-items: flex-end;
                margin-bottom: 20px; border-bottom: 1px solid #333; padding-bottom: 15px;
            }}
            .ticker-info {{ display: flex; flex-direction: column; }}
            .ticker-name {{ font-size: 24px; font-weight: 800; color: #ffffff; line-height: 1.2; }}
            .ticker-code {{ font-size: 14px; color: #9ca3af; font-family: monospace; font-weight: 400; margin-top: 4px; }}
            .mode-badge {{ display: inline-block; background: #3b82f6; color: white; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 8px; vertical-align: middle; }}
            
            .stats-box {{ font-size: 14px; color: #9ca3af; display: flex; gap: 15px; align-items: center; }}
            .stat-val {{ font-weight: 800; font-size: 18px; font-family: monospace; }}
            .win-col {{ color: #34d399; }} .lose-col {{ color: #f87171; }}

            .chart-wrapper {{
                position: relative; width: 100%; height: 400px;
                border-radius: 12px; overflow: hidden; border: 1px solid #333; background: #222;
                margin-bottom: 20px;
            }}
            .sub-chart-wrapper {{
                position: relative; width: 100%; height: 250px;
                border-radius: 12px; overflow: hidden; border: 1px solid #333; background: #222;
                margin-top: 10px;
            }}
            .price-label-box {{
                position: absolute; top: 20px; left: 50%; transform: translateX(-50%);
                background: rgba(30,30,30,0.85); border: 1px solid rgba(255,215,0,0.5);
                padding: 8px 20px; border-radius: 8px;
                text-align: center; pointer-events: none; z-index: 20; display: none;
            }}
            .price-label-title {{ color: #FBBF24; font-size: 11px; font-weight: 600; letter-spacing: 1px; margin-bottom: 2px; }}
            .price-label-val {{ color: #FFD700; font-size: 24px; font-weight: 900; font-family: monospace; line-height: 1; }}

            .overlay-anim {{
                position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
                font-size: 100px; font-weight: 900; opacity: 0; pointer-events: none; z-index: 30;
                text-shadow: 0 5px 15px rgba(0,0,0,0.5); white-space: nowrap;
            }}

            .btn-group {{ display: flex; gap: 12px; margin-top: 20px; width: 100%; }}
            .game-btn {{
                flex: 1; padding: 16px; border: none; border-radius: 12px;
                font-weight: 800; font-size: 16px; cursor: pointer; transition: all 0.2s; color: #fff;
            }}
            .game-btn:hover {{ filter: brightness(1.1); transform: translateY(-2px); }}
            .game-btn:active {{ transform: translateY(0); filter: brightness(0.95); }}
            .btn-buy {{ background: linear-gradient(135deg, #34d399 0%, #10b981 100%); }}
            .btn-sell {{ background: linear-gradient(135deg, #f87171 0%, #ef4444 100%); }}
            .btn-skip {{ background: #374151; color: #d1d5db; flex: 0.4; }}

            .modal-overlay {{
                display: none; position: absolute; inset: 0;
                background: rgba(26,26,26,0.95); backdrop-filter: blur(5px);
                flex-direction: column; justify-content: center; align-items: center; z-index: 100;
                border-radius: 16px;
            }}
            .modal-content {{ background: #27272a; padding: 40px; border-radius: 20px; text-align: center; border: 1px solid #3f3f46; max-width: 90%; }}
            .result-score {{ font-size: 60px; font-weight: 900; margin: 0 0 20px 0; line-height: 1; }}
            .result-msg {{ font-size: 16px; color: #d1d5db; margin: 0 0 30px 0; line-height: 1.6; font-weight: 600; }}
            .modal-btn {{ padding: 12px 30px; background: #3b82f6; color: white; border: none; border-radius: 30px; cursor: pointer; font-size: 16px; font-weight: 800; }}

            .sub-chart-controls {{
                position: absolute; top: 10px; left: 10px; z-index: 200;
            }}
            .sub-select {{
                background: rgba(40,40,40,0.9); color: #e5e7eb; border: 1px solid #555;
                padding: 4px 8px; border-radius: 6px; font-size: 12px; outline: none; cursor: pointer;
            }}
            
            @media (max-width: 600px) {{
                .game-container {{ padding: 10px; }}
                .header {{ flex-direction: column; align-items: flex-start; gap: 10px; margin-bottom: 10px; }}
                .stats-box {{ width: 100%; justify-content: space-between; font-size: 12px; }}
                .stat-val {{ font-size: 16px; }}
                
                .chart-wrapper {{ height: 300px; margin-bottom: 10px; }}
                .sub-chart-wrapper {{ height: 150px; margin-top: 5px; }}
                
                .btn-group {{ margin-top: 10px; gap: 8px; }}
                .game-btn {{ padding: 12px; font-size: 14px; }}
                
                .price-label-val {{ font-size: 20px; }}
                .overlay-anim {{ font-size: 60px; }}
            }}
        </style>
    </head>
    <body>
        <div id="game-wrap" class="game-container">
            <div class="header">
                <div class="ticker-info">
                    <div style="display:flex; align-items:center;">
                        <span class="ticker-name">{ticker_name}</span>
                        <span class="mode-badge">{mode.upper()}</span>
                    </div>
                    <span class="ticker-code">{ticker_code}</span>
                </div>
                <div class="stats-box">
                    <div>WIN: <span id="w-val" class="stat-val win-col">0</span></div>
                    <div>LOSE: <span id="l-val" class="stat-val lose-col">0</span></div>
                    <div style="margin-left: 10px; background: #333; padding: 4px 10px; border-radius: 6px;">
                        REMAIN: <span id="r-val" class="stat-val" style="color: #fbbf24;">{len(data['tgt']['c'])}</span>
                    </div>
                </div>
            </div>

            <div class="chart-wrapper">
                <div id="chart-area" style="width:100%; height:100%;"></div>
                <div id="price-label" class="price-label-box">
                    <div class="price-label-title">次の始値</div>
                    <div id="price-val" class="price-label-val">----</div>
                </div>
                <div id="ov-anim" class="overlay-anim"></div>
            </div>

            <div class="sub-chart-wrapper">
                <div class="sub-chart-controls">
                    <select id="sub-chart-select" class="sub-select">
                        {options_html}
                    </select>
                </div>
                <div id="sub-chart-area" style="width:100%; height:100%;"></div>
            </div>

            <div class="btn-group">
                <button id="btn-up" class="game-btn btn-buy">▲ BUY</button>
                <button id="btn-skip" class="game-btn btn-skip">SKIP</button>
                <button id="btn-down" class="game-btn btn-sell">▼ SELL</button>
            </div>
            
            <div id="res-modal" class="modal-overlay">
                <div class="modal-content">
                    <div style="font-size:18px; font-weight:800; color:#a1a1aa; margin-bottom:10px;">ACCURACY RATE</div>
                    <div id="score-val" class="result-score"></div>
                    <div id="msg-val" class="result-msg"></div> 
                    <div style="display:flex; gap:10px; justify-content:center; margin-top:20px;">
                        <button id="btn-retry" class="modal-btn" style="background:#555;">もう一度</button>
                        <button id="btn-next" class="modal-btn">次へ</button>
                        <button onclick="document.getElementById('res-modal').style.display='none'" class="modal-btn" style="background:transparent; border:1px solid #555;">閉じる</button>
                    </div>
                </div>
            </div>
        </div>

        <script>
        (function(){{
            const d = {json_data};
            const subDMap = {json_sub_map}; 
            const subIntervals = {json_sub_intervals};
            const MSGS = {json_msgs};
            const ROUND_LEN = 20;

            let startIdx = 0; 
            let idx = 0;      
            let w = 0, l = 0;
            let ac = null; let priceLine = null;
            let currentSubKey = null;

            // === Main Chart ===
            const chart = LightweightCharts.createChart(document.getElementById('chart-area'), {{
                layout: {{ backgroundColor: '#222', textColor: '#9ca3af', fontFamily: "'Inter', sans-serif" }},
                grid: {{ vertLines: {{ visible: false }}, horzLines: {{ visible: true, color: '#333' }} }},
                timeScale: {time_scale_opts},
                rightPriceScale: {{ borderColor: '#333', scaleMargins: {{ top: 0.1, bottom: 0.2 }} }},
                crosshair: {{ vertLine: {{ color: '#555', labelBackgroundColor: '#555' }}, horzLine: {{ color: '#555', labelBackgroundColor: '#555' }} }}
            }});

            const sM75 = chart.addLineSeries({{ color: '#a855f7', lineWidth: 1, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false, priceScaleId: 'right' }});
            const sM25 = chart.addLineSeries({{ color: '#34d399', lineWidth: 1, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false, priceScaleId: 'right' }});
            const sM5  = chart.addLineSeries({{ color: '#facc15', lineWidth: 1, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false, priceScaleId: 'right' }});
            
            const sC = chart.addCandlestickSeries({{ 
                upColor: '#10b981', downColor: '#f43f5e', 
                borderUpColor: '#10b981', borderDownColor: '#f43f5e', 
                wickUpColor: '#10b981', wickDownColor: '#f43f5e',
                lastValueVisible: false, priceLineVisible: false 
            }});
            
            const sNextOpen = chart.addCandlestickSeries({{ 
                upColor: '#FFD700', downColor: '#FFD700', borderUpColor: '#FFD700', borderDownColor: '#FFD700', wickUpColor: '#FFD700', wickDownColor: '#FFD700',
                lastValueVisible: false, priceLineVisible: false 
            }});
            
            const sV = chart.addHistogramSeries({{ 
                priceFormat: {{ type: 'volume' }}, priceScaleId: '', scaleMargins: {{ top: 0.8, bottom: 0 }},
                lastValueVisible: false, priceLineVisible: false 
            }});

            // === Sub Chart ===
            const subChart = LightweightCharts.createChart(document.getElementById('sub-chart-area'), {{
                layout: {{ backgroundColor: '#222', textColor: '#9ca3af', fontFamily: "'Inter', sans-serif" }},
                grid: {{ vertLines: {{ visible: false }}, horzLines: {{ visible: true, color: '#333' }} }},
                rightPriceScale: {{ borderColor: '#333' }},
                timeScale: {{ borderVisible: false }}
            }});
            
            const ssM75 = subChart.addLineSeries({{ color: '#a855f7', lineWidth: 1, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false }});
            const ssM25 = subChart.addLineSeries({{ color: '#34d399', lineWidth: 1, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false }});
            const ssM5  = subChart.addLineSeries({{ color: '#facc15', lineWidth: 1, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false }});
            
            const ssC = subChart.addCandlestickSeries({{ 
                upColor: '#10b981', downColor: '#f43f5e', 
                borderUpColor: '#10b981', borderDownColor: '#f43f5e', 
                wickUpColor: '#10b981', wickDownColor: '#f43f5e'
            }});

            function loadSubChart(key, currentMainTime, currentMainCData) {{
                currentSubKey = key;
                const sd = subDMap[key];
                if (!sd) return;
                
                const intervalSec = subIntervals[key];
                
                // Helper: TS -> JST YYYY-MM-DD
                const getJSTDateStr = (ts) => {{
                    // Treat timestamp as UTC to recover JST Naive components
                    const d = new Date(ts * 1000);
                    const y = d.getUTCFullYear();
                    const m = ('0' + (d.getUTCMonth() + 1)).slice(-2);
                    const day = ('0' + d.getUTCDate()).slice(-2);
                    return `${{y}}-${{m}}-${{day}}`;
                }};
                
                // Helper: Get start of period date string
                const getStartOfPeriod = (dateStr, type) => {{
                    const parts = dateStr.split('-');
                    const y = parseInt(parts[0]), m = parseInt(parts[1])-1, d = parseInt(parts[2]);
                    // Create UTC date to avoid local TZ issues
                    const cur = new Date(Date.UTC(y, m, d));
                    
                    if (type === '週足' || type === '1wk') {{
                        // Monday based
                        const dayVal = cur.getUTCDay(); // 0=Sun, 1=Mon
                        const diff = (dayVal === 0 ? 6 : dayVal - 1);
                        cur.setUTCDate(cur.getUTCDate() - diff);
                    }} else if (type === '月足' || type === '1mo') {{
                        cur.setUTCDate(1);
                    }}
                    // return YYYY-MM-DD
                    const yy = cur.getUTCFullYear();
                    const mm = ('0' + (cur.getUTCMonth() + 1)).slice(-2);
                    const dd = ('0' + cur.getUTCDate()).slice(-2);
                    return `${{yy}}-${{mm}}-${{dd}}`;
                }};

                let filteredC = [], filteredM5 = [], filteredM25 = [], filteredM75 = [];
                
                // Determine context
                let isIntradayMain = false;
                let cutoffDateStr = null;

                if (currentMainTime) {{
                    if (typeof currentMainTime === 'number') {{
                        isIntradayMain = true;
                        cutoffDateStr = getJSTDateStr(currentMainTime);
                    }} else {{
                        cutoffDateStr = currentMainTime;
                    }}
                }}

                if (currentMainTime) {{
                    if (intervalSec > 0) {{
                         // === INTRADAY SUB-CHART (e.g. 5m) ===
                         const bucketStart = Math.floor(currentMainTime / intervalSec) * intervalSec;
                         const checkHist = (t) => t < bucketStart;
                         
                         for(let i=0; i<sd.c.length; i++) {{
                            if(checkHist(sd.c[i].time)) {{
                                filteredC.push(sd.c[i]);
                                filteredM5.push(sd.m5[i]);
                                filteredM25.push(sd.m25[i]);
                                filteredM75.push(sd.m75[i]);
                            }}
                        }}
                        
                        // Synthesize Forming
                        if (currentMainCData) {{
                            let formO=null, formH=-Infinity, formL=Infinity, formC=null;
                            let found = false;
                            for (let i = currentMainCData.length - 1; i >= 0; i--) {{
                                const c = currentMainCData[i];
                                if (c.time < bucketStart) break;
                                if (!found) {{ formC = c.close; found=true; }}
                                formO = c.open;
                                formH = Math.max(formH, c.high);
                                formL = Math.min(formL, c.low);
                            }}
                            if (found) {{
                                filteredC.push({{ time: bucketStart, open: formO, high: formH, low: formL, close: formC }});
                            }}
                        }}
                        
                    }} else {{
                        // === DAILY/WEEKLY SUB-CHART ===
                        
                        // Default startOfPeriod is the cutoff itself (Today)
                        let startOfPeriod = cutoffDateStr;
                        
                        // If Monthly/Weekly, we need to find the FIRST day of that period
                        // because valid historical bars must be strictly before that first day.
                        if (key === '週足' || key === '月足' || key === '1wk' || key === '1mo') {{
                            startOfPeriod = getStartOfPeriod(cutoffDateStr, key);
                        }}
                        
                        // Filter: strictly less than start of current period
                        const check = (t) => t < startOfPeriod;
                        
                        for(let i=0; i<sd.c.length; i++) {{
                            if(check(sd.c[i].time)) {{
                                filteredC.push(sd.c[i]);
                                filteredM5.push(sd.m5[i]);
                                filteredM25.push(sd.m25[i]);
                                filteredM75.push(sd.m75[i]);
                            }}
                        }}
                        
                        // Synthesize Forming Candle
                        // We aggregate either from Intraday data (if main is Intraday)
                        // OR from Daily data (if main is Daily).
                        
                        if (currentMainCData) {{
                            let formO=null, formH=-Infinity, formL=Infinity, formC=null;
                            let found = false;
                            
                            // Iterate backwards
                            for (let i = currentMainCData.length - 1; i >= 0; i--) {{
                                const c = currentMainCData[i];
                                let cDate;
                                if (isIntradayMain) {{
                                     cDate = getJSTDateStr(c.time);
                                }} else {{
                                     cDate = c.time;
                                }}
                                
                                // Stop if we go before the start of the current period
                                if (cDate < startOfPeriod) break;
                                
                                // Accumulate
                                if (!found) {{ formC = c.close; found=true; }}
                                formO = c.open;
                                formH = Math.max(formH, c.high);
                                formL = Math.min(formL, c.low);
                            }}
                            
                            if (found) {{
                                filteredC.push({{ time: startOfPeriod, open: formO, high: formH, low: formL, close: formC }});
                            }}
                        }}
                    }}
                }} else {{
                    // Initial / No Context
                     filteredC = sd.c; filteredM5=sd.m5; filteredM25=sd.m25; filteredM75=sd.m75;
                }}

                ssC.setData(filteredC);
                ssM5.setData(filteredM5);
                ssM25.setData(filteredM25);
                ssM75.setData(filteredM75);
                
                if (!currentMainTime) {{
                    const total = filteredC.length;
                    if (total > 0) {{
                        const fromIdx = Math.max(0, total - 100);
                        subChart.timeScale().setVisibleLogicalRange({{ from: fromIdx, to: total + 4 }});
                    }} else {{
                        subChart.timeScale().fitContent();
                    }}
                }}
            }}
            
            // 下部チャート切り替え event
            const sel = document.getElementById('sub-chart-select');
            if(sel) {{
                 sel.onchange = (e) => {{
                     // Get current main info
                     let curT = null;
                     let curCData = null;
                     if (idx < d.tgt.c.length) {{
                         const curData = (idx > 0) ? d.tgt.c[idx-1] : d.ctx.c[d.ctx.c.length-1];
                         curT = curData.time;
                         const currentFull = [...d.ctx.c, ...d.tgt.c.slice(0, idx)];
                         curCData = currentFull;
                     }}
                     loadSubChart(e.target.value, curT, curCData);
                 }};
                 // 初期表示
                 loadSubChart(sel.value);
            }}

            // Main Chart Functions
            function updateNextOpenDisplay() {{
                if (idx >= d.tgt.c.length) {{
                    sNextOpen.setData([]);
                    document.getElementById('price-label').style.display = 'none';
                    if (priceLine) {{ sC.removePriceLine(priceLine); priceLine = null; }}
                    return;
                }}
                const nextData = d.tgt.c[idx];
                document.getElementById('price-val').innerText = nextData.open.toLocaleString();
                document.getElementById('price-label').style.display = 'block';
                if (priceLine) sC.removePriceLine(priceLine);
                priceLine = sC.createPriceLine({{ price: nextData.open, color: '#FFD700', lineWidth: 1, lineStyle: 2, axisLabelVisible: false }});
                sNextOpen.setData([{{ time: nextData.time, open: nextData.open, high: nextData.open, low: nextData.open, close: nextData.open }}]);
            }}

            function render(i) {{
                const cData = [...d.ctx.c, ...d.tgt.c.slice(0, i)];
                sC.setData(cData);
                sV.setData([...d.ctx.v, ...d.tgt.v.slice(0, i)]);
                sM5.setData([...d.ctx.m5, ...d.tgt.m5.slice(0, i)]);
                sM25.setData([...d.ctx.m25, ...d.tgt.m25.slice(0, i)]);
                sM75.setData([...d.ctx.m75, ...d.tgt.m75.slice(0, i)]);
                updateNextOpenDisplay();
                
                // Update Sub Chart
                if (currentSubKey) {{
                    // Current visible main candle time is the LAST one in cData
                    if (cData.length > 0) {{
                        const lastMain = cData[cData.length - 1];
                        loadSubChart(currentSubKey, lastMain.time, cData);
                    }}
                }}
            }}

            function initGame(baseIdx) {{
                startIdx = baseIdx;
                idx = startIdx;
                w = 0; l = 0;
                
                currentSubKey = document.getElementById('sub-chart-select').value;
                
                // Initial render
                // Identify context end time
                const ctxEnd = d.ctx.c.length > 0 ? d.ctx.c[d.ctx.c.length-1].time : null;
                // If starting mid-game (idx>0), correct time is d.tgt.c[idx-1].time
                let initTime = ctxEnd;
                if (idx > 0) {{
                    initTime = d.tgt.c[idx-1].time;
                }}
                
                const cDataInit = [...d.ctx.c, ...d.tgt.c.slice(0, idx)];
                if (cDataInit.length > 0) {{
                     initTime = cDataInit[cDataInit.length - 1].time;
                }}
                
                loadSubChart(currentSubKey, initTime, cDataInit);

                document.getElementById('w-val').innerText = '0';
                document.getElementById('l-val').innerText = '0';
                document.getElementById('r-val').innerText = ROUND_LEN;
                document.getElementById('res-modal').style.display = 'none';

                render(idx);
                // 範囲調整
                const totalVisible = d.ctx.c.length + idx;
                chart.timeScale().setVisibleLogicalRange({{ from: totalVisible - 50, to: totalVisible + 5 }});
            }}

            initGame(0);

            function beep(t) {{
                try {{
                    if(!ac) ac=new(window.AudioContext||window.webkitAudioContext)();
                    if(ac.state==='suspended') ac.resume();
                    const o=ac.createOscillator(), g=ac.createGain();
                    o.connect(g); g.connect(ac.destination);
                    const n=ac.currentTime;
                    if(t==='w') {{ o.freq.setValueAtTime(880,n); o.freq.expRampToValueAtTime(1760,n+.1); g.gain.setValueAtTime(.1,n); g.gain.linRampToValueAtTime(0,n+.4); }}
                    else if(t==='l') {{ o.type='sawtooth'; o.freq.setValueAtTime(150,n); g.gain.setValueAtTime(.1,n); g.gain.linRampToValueAtTime(0,n+.3); }}
                    else {{ o.type='square'; o.freq.setValueAtTime(500,n); g.gain.setValueAtTime(.05,n); g.gain.linRampToValueAtTime(0,n+.1); }}
                    o.start(n); o.stop(n+(t==='w'?.4:t==='l'?.3:.1));
                }} catch(e){{}}
            }}

            async function animateCandle(c) {{
                const sleep = ms => new Promise(r => setTimeout(r, ms));
                const steps = 8; 
                const wait = 15;
                const isYang = c.close >= c.open;
                
                const upd = (o, h, l, cl) => sC.update({{ time: c.time, open: o, high: h, low: l, close: cl }});

                if (isYang) {{
                    // O -> L
                    for(let i=1; i<=steps; i++) {{
                        const p = c.open + (c.low - c.open) * (i/steps);
                        upd(c.open, c.open, p, p);
                        await sleep(wait);
                    }}
                    // L -> H
                    for(let i=1; i<=steps; i++) {{
                        const p = c.low + (c.high - c.low) * (i/steps);
                        // p is current price. H is max(open, p), L is low
                        let curH = Math.max(c.open, p);
                        upd(c.open, curH, c.low, p);
                        await sleep(wait);
                    }}
                    // H -> C
                    for(let i=1; i<=steps; i++) {{
                        const p = c.high + (c.close - c.high) * (i/steps);
                        upd(c.open, c.high, c.low, p);
                        await sleep(wait);
                    }}
                }} else {{
                    // O -> H
                    for(let i=1; i<=steps; i++) {{
                        const p = c.open + (c.high - c.open) * (i/steps);
                        upd(c.open, p, c.open, p);
                        await sleep(wait);
                    }}
                    // H -> L
                    for(let i=1; i<=steps; i++) {{
                        const p = c.high + (c.low - c.high) * (i/steps);
                        // p is current price. L is min(open, p)
                        let curL = Math.min(c.open, p);
                        upd(c.open, c.high, curL, p);
                        await sleep(wait);
                    }}
                    // L -> C
                    for(let i=1; i<=steps; i++) {{
                        const p = c.low + (c.close - c.low) * (i/steps);
                        upd(c.open, c.high, c.low, p);
                        await sleep(wait);
                    }}
                }}
            }}

            function setBtns(disabled) {{
                document.getElementById('btn-up').disabled = disabled;
                document.getElementById('btn-skip').disabled = disabled;
                document.getElementById('btn-down').disabled = disabled;
                if(disabled) {{
                    document.getElementById('btn-up').style.opacity = 0.5;
                    document.getElementById('btn-skip').style.opacity = 0.5;
                    document.getElementById('btn-down').style.opacity = 0.5;
                }} else {{
                    document.getElementById('btn-up').style.opacity = 1;
                    document.getElementById('btn-skip').style.opacity = 1;
                    document.getElementById('btn-down').style.opacity = 1;
                }}
            }}

            async function playTurn(act) {{
                if(idx >= d.tgt.c.length) return;
                setBtns(true);

                const next=d.tgt.c[idx];
                const isUp=next.close>=next.open;
                let txt='SKIP', col='#9ca3af', snd='s';
                
                if(act!=='skip') {{
                    const win=(act==='up'&&isUp)||(act==='down'&&!isUp);
                    if(win) {{ w++; txt='⭕'; col='#34d399'; snd='w'; }}
                    else {{ l++; txt='❌'; col='#f87171'; snd='l'; }}
                }}
                beep(snd);

                const ov=document.getElementById('ov-anim');
                ov.innerText=txt; ov.style.color=col;
                ov.style.transition='none'; ov.style.opacity=1; ov.style.transform='translate(-50%,-50%) scale(1.2)';
                requestAnimationFrame(()=>{{
                    setTimeout(()=>{{ ov.style.transition='all 1s ease-out'; ov.style.opacity=0; ov.style.transform='translate(-50%,-50%) scale(0.8)'; }}, 50);
                }});

                if (act !== 'skip') {{
                   await animateCandle(next);
                }}

                document.getElementById('w-val').innerText=w;
                document.getElementById('l-val').innerText=l;
                
                idx++;
                render(idx);
                
                // 残り回数計算: 現在のラウンド終了まで何回か
                const playedInRound = idx - startIdx;
                document.getElementById('r-val').innerText = ROUND_LEN - playedInRound;

                const totalVisible = d.ctx.c.length + idx;
                chart.timeScale().setVisibleLogicalRange({{ from: totalVisible - 50, to: totalVisible + 5 }});
                
                setBtns(false);

                // ラウンド終了判定
                if(playedInRound >= ROUND_LEN || idx >= d.tgt.c.length) {{
                    setTimeout(()=>{{
                        const total = w + l;
                        const rate = total ? Math.round(w / total * 100) : 0;
                        const sEl = document.getElementById('score-val');
                        document.getElementById('msg-val').innerText = MSGS[rate >= 80 ? 'god' : rate >= 60 ? 'pro' : rate >= 40 ? 'normal' : rate >= 20 ? 'bad' : 'disaster'][0];
                        sEl.innerText = rate + '%';
                        sEl.style.color = rate >= 50 ? '#34d399' : '#f87171';
                        
                        // ボタン制御
                        const hasNext = (idx < d.tgt.c.length);
                        document.getElementById('btn-next').style.display = hasNext ? 'inline-block' : 'none';
                    }}, 500);
                }}
            }}

            document.getElementById('btn-up').onclick = () => playTurn('up');
            document.getElementById('btn-down').onclick = () => playTurn('down');
            document.getElementById('btn-skip').onclick = () => playTurn('skip');
            document.getElementById('btn-retry').onclick = () => {{
                // 同じ期間でリトライ
                document.getElementById('res-modal').style.display='none';
                initGame(startIdx);
            }};
            document.getElementById('btn-next').onclick = () => {{
                // 次の期間へ（現在のidxからスタート）
                document.getElementById('res-modal').style.display='none';
                initGame(idx);
            }};

        }})();
        </script>
    </body>
    </html>
    """
    st.components.v1.html(html, height=800)

def main():
    if 'mode' not in st.session_state: st.session_state['mode'] = 'daily'
    if 'ticker' not in st.session_state: st.session_state['ticker'] = '7203.T'
    
    with st.sidebar:
        st.header("設定")
        t_input = st.text_input("銘柄コード (例: 7203.T)", value=st.session_state['ticker'])
        if t_input != st.session_state['ticker']:
            st.session_state['ticker'] = t_input

        m_idx = 0
        modes = ['daily', '5m', '3m', '1m']
        labels = ['日足 (スイング)', '5分足 (デイトレ)', '3分足 (スキャ)', '1分足 (秒スキャ)']
        if st.session_state['mode'] in modes:
            m_idx = modes.index(st.session_state['mode'])
        
        sel_label = st.radio("モード選択", labels, index=m_idx)
        new_mode = modes[labels.index(sel_label)]
        if new_mode != st.session_state['mode']:
            st.session_state['mode'] = new_mode
            st.rerun()

        st.markdown("---")
        st.markdown("### 遊び方")
        st.markdown("1. モードと銘柄を選んでデータ取得\n2. 「開始！」ボタンを押す\n3. 予測してBUY/SELLボタン\n4. 20回トレードで結果発表")

    st.title("Stock Training App")
    
    # データ取得
    mode = st.session_state['mode']
    ticker = st.session_state['ticker']
    
    # 期間設定
    period_map = {'daily': "10y", '5m': "60d", '3m': "7d", '1m': "7d"}
    period = period_map[mode]
    
    # データロード
    with st.spinner("データを取得中..."):
        df, err = fetch_raw_data(ticker, period, mode if mode!='daily' else '1d')
    
    if err:
        st.error(err)
        return

    # 日付選択 (データがある場合のみ)
    selected_date = None
    if mode in ['5m', '3m', '1m']:
        # 日付リスト作成
        # indexはdatetime64[ns]
        dates = sorted(list(set(df.index.strftime('%Y-%m-%d'))), reverse=True)
        if not dates:
            st.error("有効な日付データがありません")
            return
        selected_date = st.selectbox("日付選択", dates, index=0)
    elif mode == 'daily':
        # 開始日を選ぶスライダー的なもの、あるいはランダム
        # ここではシンプルにランダムな開始位置を決めるUIにはせず、
        # ユーザーが「特定の日から始めたい」要望に応えるため日付入力を設ける
        min_date = df.index.min().date()
        max_date = df.index.max().date()
        # default roughly 1 year ago
        default_date = max_date.replace(year=max_date.year-1)
        if default_date < min_date: default_date = min_date
        
        # Date Input
        selected_date_obj = st.date_input("開始日選択", value=default_date, min_value=min_date, max_value=max_date)
        selected_date = selected_date_obj.strftime('%Y-%m-%d')

    if st.button("開始！"):
        # データ加工
        data, msg = process_data(df, mode, selected_date)
        if msg:
            st.error(msg)
        else:
            ticker_name = get_japanese_name(ticker)
            
            # サブチャート用データ取得
            # 日足モード -> 週足、月足
            # 分足モード -> 5分足(自分自身だが長期表示用)、日足
            sub_map = {}
            sub_intervals = {}
            sub_data_map = {}
            
            # sub_mode_map: 表示名 -> yfinance interval
            if mode == 'daily':
                sub_mode_map = {"週足": "1wk", "月足": "1mo"}
            elif mode == '5m':
                sub_mode_map = {"日足": "1d", "週足": "1wk"}
            else: # 3m, 1m
                # 3m, 1m の場合、上位足として 5m, 日足 を見たい
                sub_mode_map = {"5分足": "5m", "日足": "1d"}

            sub_keys = list(sub_mode_map.keys())

            for label, sub_int in sub_mode_map.items():
                # サブチャートデータの取得期間
                # 分足なら直近数日、日足なら数年
                s_period = "60d" if sub_int == "5m" else "10y"
                s_df, s_err = fetch_raw_data(ticker, s_period, sub_int)
                
                if s_df is not None:
                    # サブチャートも game_end_dt 以前のデータのみにフィルタリングする必要がある？
                    # メインチャートのデータ範囲に合わせてフィルタする
                    # game_end_dt position
                    # 日足: selected_date + 20 days (approx)
                    # イントラデイ: selected_date の終端
                    
                    # 簡易的に、全データを渡してJS側で currentMainTime に基づいて表示制限する
                    # ただし未来のデータが含まれるとカンニングになるので、
                    # メインデータの「最終ターゲット日時」以降はカットしておくのが安全
                    
                    game_end_dt = df.index[-1] # default max
                    if mode == 'daily':
                         # tgt_df is last 20 days from selected_date
                         # process_data logic: tgt_df ends at (start_pos + 20)
                         # We can roughly use the fetched df's last date if we didn't slice strict
                         # But process_data slices df.
                         # Let's trust process_data's data['tgt']['c'][-1]['time']
                         # But we are in Python.
                         pass 
                    
                    # リミット処理: メインデータの末尾より未来は消す
                    if mode in ['5m', '3m', '1m']:
                         # index filtered by selected_date
                         target_mask = df.index.strftime('%Y-%m-%d') == selected_date
                         sub_tgt = df.loc[target_mask]
                         if not sub_tgt.empty:
                             game_end_dt = sub_tgt.index[-1]
                    else:
                         # Daily: df is full history normally, but we might want to restrict if selected
                         # However, for Daily subcharts (Weekly/Monthly), the timestamp is Date.
                         # We can just pass all history up to today for subcharts, 
                         # and JS checks timestamp vs current main time.
                         pass

                    # カット (Safety)
                    # s_df is timestamp indexed
                    if s_df.index.tz is None and game_end_dt.tzinfo is None:
                        s_df_cut = s_df[s_df.index <= game_end_dt]
                    else:
                        s_df_cut = s_df # fallback
                    
                    # Process sub data
                    # make_entry logic duplicated but simplified
                    is_sub_intraday = (label == "5分足") # 5m is intraday
                    sub_intervals[label] = 300 if is_sub_intraday else 0 # 5m=300sec
                    
                    s_processed = process_data(s_df_cut, sub_int, None) # mode mismatch but works for calculation
                    # process_data returns {ctx, tgt}. Merge them.
                    if s_processed[0]:
                        merged_c = s_processed[0]['ctx']['c'] + s_processed[0]['tgt']['c']
                        merged_m5 = s_processed[0]['ctx']['m5'] + s_processed[0]['tgt']['m5']
                        merged_m25 = s_processed[0]['ctx']['m25'] + s_processed[0]['tgt']['m25']
                        merged_m75 = s_processed[0]['ctx']['m75'] + s_processed[0]['tgt']['m75']
                        
                        sub_data_map[label] = {
                            "c": merged_c, "m5": merged_m5, "m25": merged_m25, "m75": merged_m75
                        }

            render_game_html(data, sub_data_map, ticker_name, ticker, mode, sub_keys, sub_intervals)

if __name__ == "__main__":
    main()
