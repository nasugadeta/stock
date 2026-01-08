import streamlit as st
import yfinance as yf
import pandas as pd
import json
import random
import string
import re
import requests  # 追加: 社名取得用

# === 設定 ===
PREDICT_DAYS = 20
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
    yfinanceのinfoが不安定なため、こちらのほうが確実です。
    """
    # コードから.Tを除去（URL作成用）
    code_only = ticker.replace('.T', '')
    url = f"https://finance.yahoo.co.jp/quote/{code_only}.T"
    
    try:
        # ブラウザのふりをしてアクセス
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=3)
        res.encoding = res.apparent_encoding
        
        if res.status_code == 200:
            # HTMLの <title>トヨタ自動車(株)【7203】... から社名を抽出
            # 正規表現で【の前までを取得
            match = re.search(r'<title>(.*?)【', res.text)
            if match:
                return match.group(1).strip()
    except:
        pass

    # 取得失敗時はyfinanceを試す（英語名になる可能性が高い）
    try:
        t = yf.Ticker(ticker)
        return t.info.get('longName', ticker)
    except:
        return ticker

@st.cache_data(ttl=3600)
def get_stock_data(code_str):
    """データ取得ロジック"""
    code_str = str(code_str).strip().upper()
    if re.match(r'^\d{4}$', code_str):
        ticker = f"{code_str}.T"
    else:
        ticker = code_str

    try:
        df = yf.download(ticker, period="2y", interval="1d", progress=False, auto_adjust=False)
    except Exception as e:
        return None, f"ダウンロードエラー: {e}"

    if df.empty: return None, "データが見つかりません。コードを確認してください。"
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    if 'Close' not in df.columns: return None, "株価データ(Close)がありません。"

    # テクニカル指標計算
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA25'] = df['Close'].rolling(25).mean()
    df['MA75'] = df['Close'].rolling(75).mean()
    df = df.dropna()

    if len(df) < PREDICT_DAYS + 50: return None, "データ不足です（表示用に最低50日分必要です）。"

    df.index = pd.to_datetime(df.index)
    df['date_str'] = df.index.strftime('%Y-%m-%d')

    ctx = df.iloc[:-PREDICT_DAYS]
    tgt = df.iloc[-PREDICT_DAYS:]

    # JSON化のためのデータ整形
    def make_c(d):
        return [{"time": r['date_str'], "open": r['Open'], "high": r['High'], "low": r['Low'], "close": r['Close']} for _, r in d.iterrows()]
    def make_v(d):
        return [{"time": r['date_str'], "value": r['Volume'], "color": 'rgba(200, 200, 200, 0.4)'} for _, r in d.iterrows()]
    def make_l(d, col):
        return [{"time": r['date_str'], "value": r[col]} for _, r in d.iterrows()]

    # 日本語社名を取得
    name = get_japanese_name(ticker)
    
    data = {
        "name": name, "code": ticker,
        "ctx": {
            "c": make_c(ctx), "v": make_v(ctx),
            "m5": make_l(ctx, 'MA5'), "m25": make_l(ctx, 'MA25'), "m75": make_l(ctx, 'MA75')
        },
        "tgt": {
            "c": make_c(tgt), "v": make_v(tgt),
            "m5": make_l(tgt, 'MA5'), "m25": make_l(tgt, 'MA25'), "m75": make_l(tgt, 'MA75')
        }
    }
    return data, None

def render_game_html(data):
    uid = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    json_data = json.dumps(data)
    json_msgs = json.dumps(MESSAGES)
    
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
            /* 社名表示スタイル */
            .ticker-name {{ 
                font-size: 24px; font-weight: 800; color: #ffffff; 
                line-height: 1.2;
            }}
            .ticker-code {{ 
                font-size: 14px; color: #9ca3af; font-family: monospace; font-weight: 400; margin-top: 4px; 
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
                    <span class="ticker-name">{data['name']}</span>
                    <span class="ticker-code">{data['code']}</span>
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
                timeScale: {{ borderColor: '#333', timeVisible: true }},
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
                
                sNextOpen.setData([{{ time: nextData.time, open: nextData.open, high: nextData.open, low: nextData.open, close: nextData.open }}]);
            }}

            function render(i) {{
                sC.setData([...d.ctx.c, ...d.tgt.c.slice(0, i)]);
                sV.setData([...d.ctx.v, ...d.tgt.v.slice(0, i)]);
                sM5.setData([...d.ctx.m5, ...d.tgt.m5.slice(0, i)]);
                sM25.setData([...d.ctx.m25, ...d.tgt.m25.slice(0, i)]);
                sM75.setData([...d.ctx.m75, ...d.tgt.m75.slice(0, i)]);
                updateNextOpenDisplay();
            }}

            render(0);
            const totalBars = d.ctx.c.length;
            chart.timeScale().setVisibleLogicalRange({{ from: totalBars - 50, to: totalBars }});

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
                chart.timeScale().scrollToPosition(0, true);

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
# 全体の余白調整用CSS
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    </style>
""", unsafe_allow_html=True)

st.title("💹 株トレードゲーム")

# 説明文
st.markdown("実際の株価データを使った**「次の足が上がるか下がるか」**を予測するゲームです。")

# ルール説明を横並びのカード風に配置
col_rule1, col_rule2, col_rule3 = st.columns(3)

with col_rule1:
    st.success("**BUY**: 陽線（始値より終値が高い）と予測", icon="📈")

with col_rule2:
    st.error("**SELL**: 陰線（始値より終値が低い）と予測", icon="📉")

with col_rule3:
    st.info("**SKIP**: 自信がない時は見送り", icon="👀")

st.markdown("---")

# 入力フォームとボタンをスタイリッシュに配置
input_col, btn_col = st.columns([1, 5])

with input_col:
    # ラベルを指定の文言に変更し、表示されるようにしました
    code = st.text_input("証券コードを入力", "7203")

with btn_col:
    # 入力欄の「証券コードを入力」という文字の分だけボタンが上にズレないよう、透明な隙間を入れて高さを揃えます
    st.markdown('<div style="height: 29px;"></div>', unsafe_allow_html=True)
    start_btn = st.button("ゲーム開始", type="primary", use_container_width=True)

# ゲーム開始処理
if start_btn:
    with st.spinner(f'{code} のデータを取得中...'):
        stock_data, error = get_stock_data(code)
    
    if error:
        st.error(error)
    else:
        st.write("") 
        game_html = render_game_html(stock_data)
        st.components.v1.html(game_html, height=650, scrolling=False)
