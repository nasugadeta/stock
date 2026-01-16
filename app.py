import streamlit as st
import yfinance as yf
import pandas as pd
import json
import random
import string
import re
import requests
from datetime import timedelta

# === 設定 ===
PREDICT_DAYS_DAILY = 20  # 日足モードでの予測期間
PREDICT_BARS_5M = 100    # 5分足モードでのプレイ本数（必要に応じて調整）

st.set_page_config(page_title="板読み株トレードゲーム", layout="wide")

# === メッセージリスト定義 ===
MESSAGES = {
    "god": [
        "未来から来たんですか？ ロト6の番号も教えてください。",
        "SEC（証券取引委員会）があなたの監視を始めました。",
        "天才現る。明日からファンドマネージャーを名乗ってください。",
        "バフェットがあなたの電話番号を知りたがっています。",
        "その透視能力、カジノでは使わないでくださいね。",
        "全知全能の神ですか？ それともチャートが壊れていますか？"
    ],
    "pro": [
        "素晴らしい！ 相場の神様があなたに微笑んでいます。",
        "今のあなたなら、目をつぶって発注しても勝てるでしょう。",
        "働いたら負け。トレードだけで生きていける才能です。",
        "ウォール街があなたをヘッドハンティングしに来ますよ。",
        "完璧な読みです。ジョージ・ソロスも裸足で逃げ出すレベル。",
        "美しいトレードです。芸術点も加算しておきます。"
    ],
    "normal": [
        "コイントスで決めても、だいたい同じ結果になりますよ。",
        "サルのダーツ投げといい勝負です。",
        "凡人ですね。手数料負けして資産が溶けるパターンです。",
        "悪くはないですが、AIに仕事を奪われるレベルです。",
        "可もなく不可もなく。記憶に残らないトレードでした。",
        "プラマイゼロ。時間の無駄でしたね。"
    ],
    "bad": [
        "養分乙。相場にお金を寄付してくれてありがとう。",
        "引退をおすすめします。真面目に。",
        "もしかして、画面を逆さまに見ていませんか？",
        "今日の損失は勉強代……にしては高すぎませんか？",
        "悪いことは言いません。定期預金にしておきましょう。",
        "あなたが買った瞬間、アルゴが売りを浴びせていますね。"
    ],
    "disaster": [
        "逆にすごい！ ここまで外す才能は稀有ですよ。",
        "あなたの『買い』は、全人類への『売り』シグナルです。",
        "PCの電源が入っていない可能性があります。確認してください。",
        "才能の無駄遣い。逆張りすれば億万長者になれます。",
        "呼吸をするように損をしていますね。",
        "お祓いに行った方がいいかもしれません。"
    ]
}

def get_japanese_name(ticker):
    """
    Yahoo!ファイナンス(日本)からスクレイピングして日本語社名を取得する
    """
    code_only = ticker.replace('.T', '')
    url = f"https://finance.yahoo.co.jp/quote/{code_only}.T"
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=3)
        res.encoding = res.apparent_encoding
        
        if res.status_code == 200:
            match = re.search(r'<title>(.*?)【', res.text)
            if match:
                return match.group(1).strip()
    except:
        pass

    try:
        t = yf.Ticker(ticker)
        return t.info.get('longName', ticker)
    except:
        return ticker

@st.cache_data(ttl=3600)
def fetch_raw_data(ticker, period, interval):
    """yfinanceから生データを取得してキャッシュする"""
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
    except Exception as e:
        return None, f"ダウンロードエラー: {e}"

    if df.empty:
        return None, "データが見つかりません。コードを確認してください。"
    
    # マルチインデックス対応（yfinance v0.2+ / v1.0+）
    if isinstance(df.columns, pd.MultiIndex):
        # Tickerレベルがあれば削除してClose, Open...だけにする
        try:
            df.columns = df.columns.get_level_values(0)
        except:
            pass
            
    # 最低限のカラムチェック
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    missing = [c for c in required if c not in df.columns]
    if missing:
        return None, f"必要なカラム({missing})が不足しています。"

    # インデックスをDatetime型に
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # タイムゾーン処理：日本時間に変換してTZ情報を削除（扱いやすくするため）
    # yfinanceは通常UTC等のTZ付きで返すが、日本の株なら基本はJST
    if df.index.tz is not None:
        df.index = df.index.tz_convert('Asia/Tokyo').tz_localize(None)

    return df, None

def process_data(df, mode, selected_date_str=None):
    """
    取得したデータをゲーム用に加工する
    mode: 'daily' or '5m'
    selected_date_str: 'YYYY-MM-DD' (5mモード用)
    """
    # テクニカル指標計算
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA25'] = df['Close'].rolling(25).mean()
    df['MA75'] = df['Close'].rolling(75).mean()
    # NaN除去（MA計算分）
    df = df.dropna()

    ctx_df = pd.DataFrame()
    tgt_df = pd.DataFrame()

    if mode == 'daily':
        if len(df) < PREDICT_DAYS_DAILY + 50:
            return None, "データ不足です（表示用に最低50日分必要です）。"
        
        # 直近PREDICT_DAYS_DAILY分をターゲット、それ以前をコンテキスト
        ctx_df = df.iloc[:-PREDICT_DAYS_DAILY]
        tgt_df = df.iloc[-PREDICT_DAYS_DAILY:]

    elif mode == '5m':
        # 日付フィルタリング
        if not selected_date_str:
            return None, "日付が選択されていません。"
        
        # 選択された日付のデータを抽出
        target_mask = df.index.strftime('%Y-%m-%d') == selected_date_str
        tgt_df = df.loc[target_mask]
        
        if tgt_df.empty:
            return None, f"選択された日付({selected_date_str})のデータがありません。"

        # コンテキストデータ（選択日より前のデータ）
        # 直近のつながりを重視して、過去N本（例えば200本）を取得
        cutoff_time = tgt_df.index[0]
        ctx_df = df[df.index < cutoff_time].tail(200) # チャート表示用に過去200本あれば十分

        # もしコンテキストが空でもゲームは開始できるようにする（朝イチ想定）
    
    # JSON化ブロック作成ヘルパー
    def make_entry(t_idx, r, is_intraday):
        # 軽量チャート用時刻フォーマット
        # 日足: 'YYYY-MM-DD' 文字列
        # 分足: Unix Timestamp (秒)
        if is_intraday:
            # タイムスタンプ(秒)
            t_val = int(t_idx.timestamp()) + 32400 # JST補正(Lightweight ChartsはUTC想定で動く場合があるため、表示時間を合わせる工夫が必要だが、timestampならローカル時間設定依存)
            # Lightweight ChartsはデフォルトでUTC扱いだが、useMasculine:trueなど設定がある。
            # シンプルにTimestampを渡すとUTCとして扱われる。
            # 今回はJSTのネイティブdatetimeに変換済→timestamp()はUTC基準の秒数を返す。
            # これでチャート側がタイムゾーン設定を持てば合うはずだが、
            # 簡易的に UTC+9時間の秒数を足して「UTCとして渡す」とチャート上でJST時間に見えるハックがよく使われる。
            # ここではシンプルにそのまま渡して、チャート設定で対応するか、JST時間をUTCとして渡す（ハック）で行く。
            # 日本株専用なら、JST時間をあたかもUTCかのようにtimestamp化するのが手っ取り早い。
            t_val = int(t_idx.timestamp()) + 9*3600 
        else:
            t_val = t_idx.strftime('%Y-%m-%d')

        return {
            "time": t_val,
            "open": r['Open'], "high": r['High'], "low": r['Low'], "close": r['Close'],
            "vol": r['Volume'],
            "ma5": r['MA5'], "ma25": r['MA25'], "ma75": r['MA75']
        }

    is_intraday = (mode == '5m')

    # コンテキストデータ変換
    ctx_data = {
        "c": [], "v": [], "m5": [], "m25": [], "m75": []
    }
    for t, r in ctx_df.iterrows():
        e = make_entry(t, r, is_intraday)
        ctx_data["c"].append({"time": e["time"], "open": e["open"], "high": e["high"], "low": e["low"], "close": e["close"]})
        ctx_data["v"].append({"time": e["time"], "value": e["vol"], "color": 'rgba(200, 200, 200, 0.4)'})
        ctx_data["m5"].append({"time": e["time"], "value": e["ma5"]})
        ctx_data["m25"].append({"time": e["time"], "value": e["ma25"]})
        ctx_data["m75"].append({"time": e["time"], "value": e["ma75"]})

    # ターゲットデータ変換
    tgt_data = {
        "c": [], "v": [], "m5": [], "m25": [], "m75": []
    }
    for t, r in tgt_df.iterrows():
        e = make_entry(t, r, is_intraday)
        tgt_data["c"].append({"time": e["time"], "open": e["open"], "high": e["high"], "low": e["low"], "close": e["close"]})
        tgt_data["v"].append({"time": e["time"], "value": e["vol"], "color": 'rgba(200, 200, 200, 0.4)'})
        tgt_data["m5"].append({"time": e["time"], "value": e["ma5"]})
        tgt_data["m25"].append({"time": e["time"], "value": e["ma25"]})
        tgt_data["m75"].append({"time": e["time"], "value": e["ma75"]})

    return {
        "ctx": ctx_data,
        "tgt": tgt_data
    }, None


def render_game_html(data, ticker_name, ticker_code, mode):
    uid = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    json_data = json.dumps(data)
    json_msgs = json.dumps(MESSAGES)
    
    # モードに応じて時間スケールの設定を変える
    # 日足: timeVisible: true, secondsVisible: false
    # 5分足: timeVisible: true, secondsVisible: false (分まで表示)
    time_scale_opts = "{ timeVisible: true, secondsVisible: false }"
    if mode == '5m':
        time_scale_opts = "{ timeVisible: true, secondsVisible: false, tickMarkFormatter: (time, tickMarkType, locale) => { const d = new Date(time * 1000); return d.getUTCHours().toString().padStart(2,'0') + ':' + d.getUTCMinutes().toString().padStart(2,'0'); } }"

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
            .ticker-info {{ 
                display: flex; flex-direction: column; 
            }}
            .ticker-name {{ 
                font-size: 24px; font-weight: 800; color: #ffffff; 
                line-height: 1.2;
            }}
            .ticker-code {{ 
                font-size: 14px; color: #9ca3af; font-family: monospace; font-weight: 400; margin-top: 4px; 
            }}
            .mode-badge {{
                display: inline-block; background: #3b82f6; color: white; 
                font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 8px; vertical-align: middle;
            }}
            
            .stats-box {{ font-size: 14px; color: #9ca3af; display: flex; gap: 15px; align-items: center; }}
            .stat-val {{ font-weight: 800; font-size: 18px; font-family: monospace; }}
            .win-col {{ color: #34d399; }} .lose-col {{ color: #f87171; }}

            .chart-wrapper {{
                position: relative; width: 100%; height: 450px;
                border-radius: 12px; overflow: hidden; border: 1px solid #333; background: #222;
            }}

            .price-label-box {{
                position: absolute; top: 20px; left: 50%; transform: translateX(-50%);
                background: rgba(30, 30, 30, 0.85); 
                border: 1px solid rgba(255, 215, 0, 0.5);
                padding: 8px 20px; border-radius: 8px;
                text-align: center; pointer-events: none; z-index: 20; display: none;
                box-shadow: 0 4px 10px rgba(0,0,0,0.5);
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
                font-weight: 800; font-size: 16px; cursor: pointer; transition: all 0.2s;
                color: #fff;
            }}
            .game-btn:hover {{ filter: brightness(1.1); transform: translateY(-2px); }}
            .game-btn:active {{ transform: translateY(0); filter: brightness(0.95); }}
            .btn-buy {{ background: linear-gradient(135deg, #34d399 0%, #10b981 100%); }}
            .btn-sell {{ background: linear-gradient(135deg, #f87171 0%, #ef4444 100%); }}
            .btn-skip {{ background: #374151; color: #d1d5db; flex: 0.4; }}

            .modal-overlay {{
                display: none; position: absolute; inset: 0;
                background: rgba(26, 26, 26, 0.95); backdrop-filter: blur(5px);
                flex-direction: column; justify-content: center; align-items: center; z-index: 100;
                border-radius: 16px;
            }}
            .modal-content {{
                background: #27272a; padding: 40px; border-radius: 20px; text-align: center;
                border: 1px solid #3f3f46; box-shadow: 0 20px 40px rgba(0,0,0,0.4);
                max-width: 90%;
            }}
            .result-score {{ font-size: 60px; font-weight: 900; margin: 0 0 20px 0; line-height: 1; }}
            .result-msg {{ font-size: 16px; color: #d1d5db; margin: 0 0 30px 0; line-height: 1.6; font-weight: 600; }}
            .modal-btn {{
                padding: 12px 30px; background: #3b82f6; color: white; border: none;
                border-radius: 30px; cursor: pointer; font-size: 16px; font-weight: 800;
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
            let idx = 0;
            let w = 0, l = 0;
            let ac = null;
            let priceLine = null;

            const chart = LightweightCharts.createChart(document.getElementById('chart-area'), {{
                layout: {{ backgroundColor: '#222', textColor: '#9ca3af', fontFamily: "'Inter', sans-serif" }},
                grid: {{ vertLines: {{ visible: false }}, horzLines: {{ visible: true, color: '#333' }} }},
                timeScale: {time_scale_opts},
                rightPriceScale: {{ borderColor: '#333', scaleMargins: {{ top: 0.1, bottom: 0.2 }} }},
                crosshair: {{ vertLine: {{ color: '#555', labelBackgroundColor: '#555' }}, horzLine: {{ color: '#555', labelBackgroundColor: '#555' }} }}
            }});

            const sM75 = chart.addLineSeries({{ 
                color: '#a855f7', lineWidth: 1, 
                crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false 
            }});
            const sM25 = chart.addLineSeries({{ 
                color: '#34d399', lineWidth: 1, 
                crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false 
            }});
            const sM5  = chart.addLineSeries({{ 
                color: '#facc15', lineWidth: 1, 
                crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false 
            }});
            
            const sC = chart.addCandlestickSeries({{ 
                upColor: '#10b981', downColor: '#f43f5e', 
                borderUpColor: '#10b981', borderDownColor: '#f43f5e', 
                wickUpColor: '#10b981', wickDownColor: '#f43f5e',
                lastValueVisible: false, priceLineVisible: false 
            }});
            
            const sNextOpen = chart.addCandlestickSeries({{ 
                upColor: '#FFD700', downColor: '#FFD700', 
                borderUpColor: '#FFD700', borderDownColor: '#FFD700', 
                wickUpColor: '#FFD700', wickDownColor: '#FFD700',
                lastValueVisible: false, priceLineVisible: false 
            }});
            
            const sV = chart.addHistogramSeries({{ 
                priceFormat: {{ type: 'volume' }}, priceScaleId: '', 
                scaleMargins: {{ top: 0.8, bottom: 0 }},
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
                
                priceLine = sC.createPriceLine({{ 
                    price: nextData.open, 
                    color: '#FFD700', 
                    lineWidth: 1,      
                    lineStyle: 2,      
                    axisLabelVisible: false,
                }});
                
                // 次の足の始値を黄色い十字線で表示
                sNextOpen.setData([{{ time: nextData.time, open: nextData.open, high: nextData.open, low: nextData.open, close: nextData.open }}]);
            }}

            function render(i) {{
                // コンテキストデータ＋ターゲットのi番目までを表示
                const cData = [...d.ctx.c, ...d.tgt.c.slice(0, i)];
                sC.setData(cData);
                sV.setData([...d.ctx.v, ...d.tgt.v.slice(0, i)]);
                sM5.setData([...d.ctx.m5, ...d.tgt.m5.slice(0, i)]);
                sM25.setData([...d.ctx.m25, ...d.tgt.m25.slice(0, i)]);
                sM75.setData([...d.ctx.m75, ...d.tgt.m75.slice(0, i)]);
                updateNextOpenDisplay();
            }}

            // 初期描画
            render(0);
            
            // 表示範囲の調整（コンテキストの最後50本〜現在地までなどを表示）
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

            function playTurn(act) {{
                if(idx>=d.tgt.c.length) return;
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

                document.getElementById('w-val').innerText=w;
                document.getElementById('l-val').innerText=l;
                document.getElementById('r-val').innerText=d.tgt.c.length-(idx+1);

                idx++;
                render(idx);
                // 常に最新の足が見えるように右端へスクロール
                // chart.timeScale().scrollToPosition(0, true);
                
                // より自然な追従：最新の足が右側に来るようにRangeをずらす
                const totalVisible = d.ctx.c.length + idx;
                chart.timeScale().setVisibleLogicalRange({{ from: totalVisible - 50, to: totalVisible + 5 }});

                if(idx>=d.tgt.c.length) {{
                    setTimeout(()=>{{
                        const total = w + l;
                        const rate = total ? Math.round(w / total * 100) : 0;
                        const sEl = document.getElementById('score-val');
                        const mEl = document.getElementById('msg-val');
                        sEl.innerText = rate + '%';
                        sEl.style.color = rate >= 50 ? '#34d399' : '#f87171';
                        
                        let cat = 'disaster';
                        if (rate >= 80) cat = 'god';
                        else if (rate >= 60) cat = 'pro';
                        else if (rate >= 40) cat = 'normal';
                        else if (rate >= 20) cat = 'bad';
                        
                        const list = MSGS[cat];
                        mEl.innerText = list[Math.floor(Math.random() * list.length)];
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

# === Streamlit UI ===
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .stAlert { height: 100%; }
    .stSelectbox { margin-bottom: 0px; }
    </style>
""", unsafe_allow_html=True)

st.title("💹 株トレードゲーム")
st.markdown("実際の株価データを使った**「次の足が上がるか下がるか」**を予測するゲームです。")

# サイドバー設定
with st.sidebar:
    st.header("設定")
    ticker_input = st.text_input("証券コード", "7203.T")
    
    mode = st.radio("モード選択", ["日足 (Daily)", "5分足 (5-minute)"], index=0)
    
    selected_date_opt = None
    
    # モードに応じたデータ取得（UI表示用）
    if "5分" in mode:
        game_mode = '5m'
        st.info("5分足モード：過去60日分のデータから、プレイする日付を選択します。")
        # まず日付リストを取得するためにデータをフェッチ（キャッシュされる）
        with st.spinner("日付リストを取得中..."):
            df_check, err = fetch_raw_data(ticker_input, "60d", "5m")
            if df_check is not None and not df_check.empty:
                # 日付リスト作成
                dates = sorted(list(set(df_check.index.strftime('%Y-%m-%d'))), reverse=True)
                selected_date_opt = st.selectbox("プレイする日付を選択", dates)
            elif err:
                st.error(err)
    else:
        game_mode = 'daily'
        st.info("日足モード：過去2年分のデータを使用します。")

# ルール説明
col_rule1, col_rule2, col_rule3 = st.columns(3)
with col_rule1:
    st.success("**BUY**: 陽線 (始 < 終)", icon="📉")
with col_rule2:
    st.markdown("""
        <div style="background-color: rgba(150, 150, 150, 0.15); border: 1px solid rgba(150, 150, 150, 0.3); padding: 16px; border-radius: 8px; color: inherit; display: flex; align-items: center;">
            <span style="font-size: 1.25rem; margin-right: 12px;">👀</span>
            <div style="font-size: 0.9rem;"><strong>SKIP</strong>: 自信がない時は見送り</div>
        </div>
    """, unsafe_allow_html=True)
with col_rule3:
    st.error("**SELL**: 陰線 (始 > 終)", icon="📉")

st.divider()

# メイン操作エリア
c1, c2 = st.columns([2, 1])
with c1:
    st.write(f"**対象銘柄**: {ticker_input} / **モード**: {game_mode.upper()}")
with c2:
    start_btn = st.button("ゲームスタート / リセット", type="primary", use_container_width=True)

if start_btn or 'game_active' in st.session_state:
    st.session_state['game_active'] = True
    
    # データ取得＆加工
    with st.spinner("ゲームデータを生成中..."):
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
