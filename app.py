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
PREDICT_BARS_5M = 100

st.set_page_config(page_title="板読み株トレードゲーム", layout="wide")

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
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
    except Exception as e: return None, f"エラー: {e}"
    if df.empty: return None, "データなし"
    
    if isinstance(df.columns, pd.MultiIndex):
        try: df.columns = df.columns.get_level_values(0)
        except: pass
            
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not all(c in df.columns for c in required): return None, "データ不足"

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
        ctx_df = df.iloc[:-PREDICT_DAYS_DAILY]
        tgt_df = df.iloc[-PREDICT_DAYS_DAILY:]

    elif mode == '5m':
        if not selected_date_str: return None, "日付未選択"
        target_mask = df.index.strftime('%Y-%m-%d') == selected_date_str
        tgt_df = df.loc[target_mask]
        if tgt_df.empty: return None, "選択日のデータなし"
        
        cutoff_time = tgt_df.index[0]
        ctx_df = df[df.index < cutoff_time].tail(200)

    is_intraday = (mode == '5m')

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

def render_game_html(data, ticker_name, ticker_code, mode):
    json_data = json.dumps(data)
    json_msgs = json.dumps(MESSAGES)
    
    # 5分足の場合、時刻フォーマットをHH:mmにする
    time_scale_opts = "{ timeVisible: true, secondsVisible: false }"
    if mode == '5m':
        # useMasculine: false にして、渡されたTimestamp(UTC扱い)をそのまま表示させる
        # 15:30 などをそのまま出す
        time_scale_opts = """{
            timeVisible: true, 
            secondsVisible: false,
            tickMarkFormatter: (time, tickMarkType, locale) => {
                const d = new Date(time * 1000);
                return d.getUTCHours().toString().padStart(2,'0') + ':' + d.getUTCMinutes().toString().padStart(2,'0');
            }
        }"""

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
                position: relative; width: 100%; height: 450px;
                border-radius: 12px; overflow: hidden; border: 1px solid #333; background: #222;
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
                    <div class="price-label-title">NEXT OPEN</div>
                    <div id="price-val" class="price-label-val">----</div>
                </div>
                <div id="ov-anim" class="overlay-anim"></div>
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
                    <button onclick="document.getElementById('res-modal').style.display='none'" class="modal-btn">閉じる</button>
                </div>
            </div>
        </div>

        <script>
        (function(){{
            const d = {json_data};
            const MSGS = {json_msgs};
            let idx = 0; let w = 0, l = 0;
            let ac = null; let priceLine = null;

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
            }}

            render(0);
            if (d.ctx.c.length > 50) {{
                const totalBars = d.ctx.c.length;
                chart.timeScale().setVisibleLogicalRange({{ from: totalBars - 50, to: totalBars + 5 }});
            }} else {{
                chart.timeScale().fitContent();
            }}

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
                if(idx>=d.tgt.c.length) return;
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

                await animateCandle(next);

                document.getElementById('w-val').innerText=w;
                document.getElementById('l-val').innerText=l;
                document.getElementById('r-val').innerText=d.tgt.c.length-(idx+1);

                idx++;
                render(idx);
                
                const totalVisible = d.ctx.c.length + idx;
                chart.timeScale().setVisibleLogicalRange({{ from: totalVisible - 50, to: totalVisible + 5 }});
                
                setBtns(false);

                if(idx>=d.tgt.c.length) {{
                    setTimeout(()=>{{
                        const total = w + l;
                        const rate = total ? Math.round(w / total * 100) : 0;
                        const sEl = document.getElementById('score-val');
                        document.getElementById('msg-val').innerText = MSGS[rate >= 80 ? 'god' : rate >= 60 ? 'pro' : rate >= 40 ? 'normal' : rate >= 20 ? 'bad' : 'disaster'][0];
                        sEl.innerText = rate + '%';
                        sEl.style.color = rate >= 50 ? '#34d399' : '#f87171';
                        document.getElementById('res-modal').style.display='flex';
                    }}, 1000);
                }}
            }}

            document.getElementById('btn-up').onclick = () => playTurn('up');
            document.getElementById('btn-skip').onclick = () => playTurn('skip');
            document.getElementById('btn-down').onclick = () => playTurn('down');
        }})();
        </script>
    </body>
    </html>
    """
    return html

# === UI (Main Area) ===
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .stAlert { height: 100%; }
    </style>
""", unsafe_allow_html=True)

st.title("💹 株トレードゲーム")

# メインエリアの上部に操作系を配置
c1, c2, c3 = st.columns([1.5, 1.5, 1])

with c1:
    ticker_input = st.text_input("証券コード", "7203.T", placeholder="例: 7203.T")
    
    # 全角数字を半角に変換
    ticker_input = ticker_input.translate(str.maketrans({chr(0xFF10 + i): chr(0x30 + i) for i in range(10)}))
    ticker_input = ticker_input.strip()
    # 4桁以下の数字だけなら.Tを付与
    if re.match(r'^\d{4}$', ticker_input):
        ticker_input = f"{ticker_input}.T"
    
with c2:
    mode = st.radio("モード", ["日足", "5分足"], horizontal=True, label_visibility="collapsed")
    # ラジオボタンのラベルを消したので自前で表示などを工夫してもいいが、
    # horizontal=Trueなら「日足」「5分足」が見えるのでOK

# 5分足の場合のみ日付選択を出す
selected_date_opt = None
game_mode = 'daily'

# モード判定とUI調整
if "5分" in mode:
    game_mode = '5m'
    with st.spinner("日付データを取得中..."):
        df_check, err = fetch_raw_data(ticker_input, "60d", "5m")
        if df_check is not None and not df_check.empty:
            dates = sorted(list(set(df_check.index.strftime('%Y-%m-%d'))), reverse=True)
            with c3:
                selected_date_opt = st.selectbox("日付", dates)
        elif err:
            st.error(err)
else:
    # 日足モードの場合、c3は空または別の情報
    with c3:
        st.write("") # Spacer

st.markdown("---")

start_btn = st.button("ゲームスタート / リセット", type="primary", use_container_width=True)

# ルール説明
col_rule1, col_rule2, col_rule3 = st.columns(3)
with col_rule1: st.success("📈 **BUY**: 上昇予測")
with col_rule2: 
    st.markdown("""
    <div style="background:rgba(150,150,150,0.15); border:1px solid rgba(150,150,150,0.3); padding:16px; border-radius:8px;">
    👀 <strong>SKIP</strong>: 様子見</div>""", unsafe_allow_html=True)
with col_rule3: st.error("📉 **SELL**: 下落予測")

if start_btn or 'game_active' in st.session_state:
    st.session_state['game_active'] = True
    
    with st.spinner("データを準備中..."):
        period = "2y" if game_mode == 'daily' else "60d"
        interval = "1d" if game_mode == 'daily' else "5m"
        
        raw_df, error_msg = fetch_raw_data(ticker_input, period, interval)
        
        if error_msg:
            st.error(error_msg)
        else:
            game_data, proc_err = process_data(raw_df, game_mode, selected_date_opt)
            
            if proc_err:
                st.error(proc_err)
            else:
                comp_name = get_japanese_name(ticker_input)
                game_html = render_game_html(game_data, comp_name, ticker_input, game_mode)
                st.components.v1.html(game_html, height=680, scrolling=False)
