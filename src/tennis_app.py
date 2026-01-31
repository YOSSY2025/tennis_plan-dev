import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from datetime import time as dt_time  
from streamlit_calendar import calendar
import gspread
from google.oauth2.service_account import Credentials
import json
import time
from gspread.exceptions import APIError
from urllib.parse import quote

# ==========================================
# 1. 共通関数・設定
# ==========================================

def run_with_retry(func, *args, **kwargs):
    max_retries = 5
    for i in range(max_retries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            if i == max_retries - 1: raise e
            code = e.response.status_code
            if code == 429 or code >= 500:
                time.sleep(2 ** (i + 1))
            else:
                raise e
        except Exception as e:
            if i == max_retries - 1: raise e
            time.sleep(2)

def safe_int(val, default=0):
    try:
        if pd.isna(val) or val == "": return default
        return int(float(val))
    except:
        return default

def to_jst_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (dt + timedelta(hours=9)).date()
    except Exception:
        if isinstance(iso_str, date): return iso_str
        return datetime.strptime(str(iso_str)[:10], "%Y-%m-%d").date()

def generate_google_calendar_url(reservation_data):
    """
    予約データからGoogleカレンダー登録用URLを生成
    
    Args:
        reservation_data: 予約情報の辞書
        
    Returns:
        str: Googleカレンダー登録用URL
    """
    # タイトル生成: 🎾テニス_[施設名]
    title = f"🎾テニス_{reservation_data['facility']}"
    
    # 日時生成: YYYYMMDDTHHMMSS形式
    res_date = reservation_data['date']
    start_hour = int(safe_int(reservation_data.get('start_hour'), 9))
    start_minute = int(safe_int(reservation_data.get('start_minute'), 0))
    end_hour = int(safe_int(reservation_data.get('end_hour'), 11))
    end_minute = int(safe_int(reservation_data.get('end_minute'), 0))
    
    start_dt = datetime.combine(res_date, dt_time(start_hour, start_minute))
    end_dt = datetime.combine(res_date, dt_time(end_hour, end_minute))
    
    start_str = start_dt.strftime("%Y%m%dT%H%M%S")
    end_str = end_dt.strftime("%Y%m%dT%H%M%S")
    
    # URL生成
    base_url = "https://calendar.google.com/calendar/render"
    params = [
        "action=TEMPLATE",
        f"text={quote(title)}",
        f"dates={start_str}/{end_str}",
        "ctz=Asia/Tokyo"
    ]
    
    return f"{base_url}?{'&'.join(params)}"


# 設定: 長押しの閾値（ミリ秒）。ここを変えるとアプリ内の長押しの感度を調整できます。
LONG_PRESS_DELAY_MS = 1200  # 1200ms = 1.2秒

# ===== Google Sheets 認証 =====
GSHEET_ID = st.secrets.get("google", {}).get("GSHEET_ID")
if not GSHEET_ID:
    st.error("Secretsの設定エラー: [google] セクション内に GSHEET_ID が見つかりません。")
    st.stop()

@st.cache_resource(show_spinner=False)
def get_gsheet(sheet_id, sheet_name):
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    service_account_info = dict(st.secrets["google"])
    creds = Credentials.from_service_account_info(service_account_info, scopes=scope)
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(sheet_id).worksheet(sheet_name)
    return worksheet

try:
    worksheet = get_gsheet(GSHEET_ID, "reservations")
except Exception as e:
    st.error(f"Google Sheetへの接続に失敗しました: {e}")
    st.stop()


# ==========================================
# 2. データ読み書き
# ==========================================

@st.cache_data(ttl=15)
def load_reservations():
    data = run_with_retry(worksheet.get_all_records)
    df = pd.DataFrame(data)

    expected_cols = [
        "date","facility","status","start_hour","start_minute",
        "end_hour","end_minute","participants","absent","consider","message"
    ]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = ""

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    def _to_list_cell(x):
        if isinstance(x, (list, tuple)): return list(x)
        if pd.isna(x) or x == "": return []
        return str(x).split(";")

    for col in ["participants", "absent", "consider"]:
        df[col] = df[col].apply(_to_list_cell)

    df["message"] = df["message"].fillna("")
    return df

def save_reservations(df):
    df_to_save = df.copy()
    
    for col in ["participants", "absent", "consider"]:
        if col in df_to_save.columns:
            df_to_save[col] = df_to_save[col].apply(lambda lst: ";".join(lst) if isinstance(lst, (list, tuple)) else (lst if pd.notnull(lst) else ""))

    if "date" in df_to_save.columns:
        df_to_save["date"] = df_to_save["date"].apply(lambda d: d.isoformat() if isinstance(d, (date, datetime, pd.Timestamp)) else (str(d) if pd.notnull(d) else ""))

    df_to_save = df_to_save.where(pd.notnull(df_to_save), "")

    def _serialize_cell(v):
        if isinstance(v, (date, datetime, pd.Timestamp)): return v.isoformat()
        if isinstance(v, (list, tuple)): return ";".join(map(str, v))
        return str(v)

    values = [df_to_save.columns.values.tolist()]
    ser_df = df_to_save.map(_serialize_cell)
    values += ser_df.values.tolist()

    run_with_retry(worksheet.clear)
    run_with_retry(worksheet.update, values)
    load_reservations.clear()


# ==========================================
# 3. 抽選リマインダー
# ==========================================
@st.cache_data(ttl=3600)
def load_lottery_data_cached():
    try:
        lottery_sheet = get_gsheet(GSHEET_ID, "lottery_periods")
        records = run_with_retry(lottery_sheet.get_all_records)
        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_facilities_data():
    """
    facilitiesシートから施設情報を読み込む
    
    Returns:
        dict: {施設名: {"url": URL, "address": 住所}}
    """
    try:
        facilities_sheet = get_gsheet(GSHEET_ID, "facilities")
        records = run_with_retry(facilities_sheet.get_all_records)
        df = pd.DataFrame(records)
        
        facilities_dict = {}
        for _, row in df.iterrows():
            name = row.get("name", "")
            if name:
                facilities_dict[name] = {
                    "url": row.get("url", ""),
                    "address": row.get("address", "")
                }
        return facilities_dict
    except Exception:
        return {}

def add_facility_if_not_exists(facility_name):
    """
    施設名がfacilitiesシートに存在しない場合、追加する
    
    Args:
        facility_name: 施設名
    """
    if not facility_name:
        return
    
    try:
        facilities_sheet = get_gsheet(GSHEET_ID, "facilities")
        records = run_with_retry(facilities_sheet.get_all_records)
        df = pd.DataFrame(records)
        
        # 既存の施設名をチェック
        if "name" in df.columns and facility_name in df["name"].values:
            return  # 既に存在する
        
        # 新規追加
        new_row = {"name": facility_name, "url": "", "address": ""}
        new_df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        
        # 保存
        values = [new_df.columns.values.tolist()] + new_df.values.tolist()
        run_with_retry(facilities_sheet.clear)
        run_with_retry(facilities_sheet.update, values)
        
        # キャッシュをクリア
        load_facilities_data.clear()
    except Exception as e:
        # エラーが発生しても予約登録は続行
        pass

def check_and_show_reminders():
    df = load_lottery_data_cached()
    if df.empty: return []

    jst_now = datetime.utcnow() + timedelta(hours=9)
    today = jst_now.date()
    
    messages_to_show = []

    for _, row in df.iterrows():
        enabled_val = str(row.get("enabled", "")).lower()
        if enabled_val not in ["true", "1", "yes", "有効"]: continue

        freq = row.get("frequency", "")
        msg = row.get("messages", "")
        if not msg: continue

        is_match = False
        try:
            if freq == "monthly":
                s_day = int(row.get("start_day", 0))
                e_day = int(row.get("end_day", 32))
                if s_day <= today.day <= e_day: is_match = True
            elif freq == "weekly":
                if today.strftime("%a") in str(row.get("weekdays", "")): is_match = True
            elif freq == "yearly":
                s_month = int(row.get("start_month", 0))
                s_day = int(row.get("start_day", 0))
                e_month = int(row.get("end_month", 0))
                e_day = int(row.get("end_day", 0))
                if s_month > 0:
                    start_date = date(today.year, s_month, s_day)
                    end_date = date(today.year, e_month, e_day)
                    if start_date > end_date: 
                        if today >= start_date or today <= end_date: is_match = True
                    else:
                        if start_date <= today <= end_date: is_match = True
        except: continue

        if is_match: messages_to_show.append(msg)

    return messages_to_show


# ==========================================
# 4. 画面描画
# ==========================================
st.markdown("""
<script>
    // ポップアップが開いたら強制的に一番上にスクロールさせる
    // (MutationObserverでDOMの変化を監視)
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            const dialog = parent.document.querySelector('div[data-testid="stDialog"]');
            if (dialog) {
                dialog.scrollTop = 0; // スクロール位置をリセット
            }
        });
    });
    observer.observe(parent.document.body, { childList: true, subtree: true });
</script>

<style>
/* --- ポップアップの表示位置 --- */
div[data-testid="stDialog"] {
    align-items: flex-start !important; /* 強制的に上詰め */
    padding-top: 10px !important;       /* 上に少し余白 */
    overflow-y: auto !important;        /* 全体スクロール */
}

/* ポップアップ本体の余白調整 */
div[data-testid="stDialog"] > div[role="dialog"] {
    margin-top: 0 !important;
    margin-bottom: 50px !important;
}

/* ポップアップの×ボタンを非表示 */
div[data-testid="stDialog"] button[aria-label="Close"] {
    display: none !important;
}

/* --- アプリ全体の余白調整 --- */
.stAppViewContainer { margin-top: 0.5rem !important; }
.stApp { padding-top: 0 !important; }
.block-container { padding-top: 2.0rem !important; }
</style>
""", unsafe_allow_html=True)


st.markdown("<h3>🎾 テニスコート予約管理</h3>", unsafe_allow_html=True)

# お知らせをトグルに表示
reminder_messages = check_and_show_reminders()
if reminder_messages:
    with st.expander("📢 お知らせ", expanded=False):
        for m in reminder_messages:
            st.info(m)

# 成功メッセージの表示（toastを使用）
if 'show_success_message' in st.session_state and st.session_state['show_success_message']:
    st.toast(st.session_state['show_success_message'], icon="✅")
    st.session_state['show_success_message'] = None

df_res = load_reservations()

# --- 自動完了: 前日のイベントを完了にする（負荷対策として1回/日） ---
def auto_complete_yesterday_events():
    """前日分のイベントをステータス「完了」に変更する。

    - 同日に既に処理済みなら何もしない（セッションフラグで抑制）
    - 処理時は最新データを読み直して、昨日の未完了イベントのみを更新する（競合緩和）
    """
    today_jst = (datetime.utcnow() + timedelta(hours=9)).date()
    yesterday = today_jst - timedelta(days=1)

    # 同日に既に処理済みなら何もしない
    if st.session_state.get('auto_completed_for_date') == str(yesterday):
        return

    # 最新データを読み込み
    latest_df = load_reservations()
    if latest_df.empty:
        st.session_state['auto_completed_for_date'] = str(yesterday)
        return

    # dateが昨日かつstatusが完了でない行を検出
    mask = (latest_df['date'] == yesterday) & (latest_df['status'] != '完了')
    cnt = int(mask.sum())
    if cnt > 0:
        latest_df.loc[mask, 'status'] = '完了'
        save_reservations(latest_df)
        # 通知は不要のため表示しない

    # 処理済み日をセッションに保管
    st.session_state['auto_completed_for_date'] = str(yesterday)

# 実行（同日複数回の保存を防ぐためセッションフラグを利用）
auto_complete_yesterday_events()
# 必要なら最新データを再読み込みして描画に反映
df_res = load_reservations()

# リストの選択状態をクリアするためのカウンター
if 'list_reset_counter' not in st.session_state:
    st.session_state['list_reset_counter'] = 0

status_color = {
    "確保": {"bg":"#90ee90","text":"black"},
    "抽選中": {"bg":"#ffd966","text":"black"},
    "中止": {"bg":"#d3d3d3","text":"black"},
    "完了": {"bg":"#d3d3d3","text":"black"}
}

events = []
for idx, r in df_res.iterrows():
    raw_date = r.get("date")
    if pd.isna(raw_date) or raw_date == "": continue
    if isinstance(raw_date, str):
        try: curr_date = datetime.fromisoformat(str(raw_date)[:10]).date()
        except: continue
    else: curr_date = raw_date

    s_hour = safe_int(r.get("start_hour"), 9)
    s_min  = safe_int(r.get("start_minute"), 0)
    e_hour = safe_int(r.get("end_hour"), 11)
    e_min  = safe_int(r.get("end_minute"), 0)

    try:
        start_dt = datetime.combine(curr_date, dt_time(s_hour, s_min))
        end_dt   = datetime.combine(curr_date, dt_time(e_hour, e_min))
    except Exception: continue

    color = status_color.get(r["status"], {"bg":"#FFFFFF","text":"black"})
    title_str = f"{r['status']} {r['facility']}"

    events.append({
        "id": idx,
        "title": title_str,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "backgroundColor": color["bg"],
        "borderColor": color["bg"],
        "textColor": color["text"]
    })


# ---------------------------------------------------------
# 5. 画面表示（タブ切り替え⇒ラジオボタン切り替えに変更）
# ---------------------------------------------------------
# 表示モードが変わったらポップアップを閉じる
if 'prev_view_mode' not in st.session_state:
    st.session_state['prev_view_mode'] = None

view_mode = st.radio(
    "表示モード", 
    ["📅 カレンダー", "📋 予約リスト"], 
    horizontal=True,
    label_visibility="collapsed",
    key="view_mode_selector"
)

# モードが切り替わったらポップアップを閉じる
if st.session_state['prev_view_mode'] is not None and st.session_state['prev_view_mode'] != view_mode:
    st.session_state['is_popup_open'] = False
    st.session_state['last_click_signature'] = None
    st.session_state['active_event_idx'] = None
    st.session_state['list_reset_counter'] += 1
st.session_state['prev_view_mode'] = view_mode

# === モード1: カレンダー表示 ===
if view_mode == "📅 カレンダー":
    initial_date = datetime.now().strftime("%Y-%m-%d")
    if "clicked_date" in st.session_state and st.session_state["clicked_date"]:
        initial_date = st.session_state["clicked_date"]

    cal_key = str(initial_date)[:7]

    cal_state = calendar(
        events=events,
        options={
            "initialView": "dayGridMonth",
            "initialDate": initial_date,
            "selectable": True,
            "headerToolbar": {"left": "prev,next today", "center": "title", "right": ""},
            "eventDisplay": "block",
            "displayEventTime": False,
            "height": "auto",
            "contentHeight": "auto",
            "aspectRatio": 1.2,
            "titleFormat": {"year": "numeric", "month": "2-digit"},
            "longPressDelay": LONG_PRESS_DELAY_MS  # ミリ秒（例: 1200 = 1.2秒）
        },
        key=f"calendar_{cal_key}"
    )

# === モード2: 予約リスト表示 ===
elif view_mode == "📋 予約リスト":
    # ★重要: カレンダー変数を空にしておく（下のイベントハンドリングを無効化するため）
    cal_state = None 
    
    show_past = st.checkbox("過去の予約も表示する", value=False, key="filter_show_past")
    df_list = df_res.copy()
    
    if not df_list.empty:
        if not show_past:
            today_jst = (datetime.utcnow() + timedelta(hours=9)).date()
            df_list = df_list[df_list['date'] >= today_jst]

        def format_time_range(r):
            sh = int(safe_int(r.get('start_hour')))
            sm = int(safe_int(r.get('start_minute')))
            eh = int(safe_int(r.get('end_hour')))
            em = int(safe_int(r.get('end_minute')))
            return f"{sh:02}:{sm:02} - {eh:02}:{em:02}"
        
        df_list['時間'] = df_list.apply(format_time_range, axis=1)
        
        def format_list_col(lst):
            if isinstance(lst, list): return ", ".join(lst)
            return str(lst)
        
        # 参加者と保留を統合して表示
        def format_participants_with_consider(row):
            parts = []
            participants = row['participants'] if isinstance(row['participants'], list) else []
            consider = row['consider'] if isinstance(row['consider'], list) else []
            
            if participants:
                parts.append(", ".join(participants))
            if consider:
                parts.append(f"(保留 {", ".join(consider)})")
            
            return " ".join(parts) if parts else ""
        
        df_list['参加者'] = df_list.apply(format_participants_with_consider, axis=1)
        
        # メモ欄の<br>をスペースに変換
        df_list['message'] = df_list['message'].apply(lambda x: str(x).replace('<br>', ' ') if pd.notna(x) else '')

        def format_date_with_weekday(d):
            if not isinstance(d, (date, datetime)): return str(d)
            weekdays = ["(月)", "(火)", "(水)", "(木)", "(金)", "(土)", "(日)"]
            wd = weekdays[d.weekday()]
            return f"{d.strftime('%Y-%m-%d')} {wd}"

        df_list['日付'] = df_list['date'].apply(format_date_with_weekday)
        df_list['日時'] = df_list['日付'] + " " + df_list['時間']
        df_list['施設名'] = df_list['facility']
        df_list['ステータス'] = df_list['status']
        df_list['メモ'] = df_list['message']
        
        display_cols = ['日時', '施設名', 'ステータス', '参加者', 'メモ']

        df_display = df_list[display_cols]
        if '日時' in df_display.columns:
            df_display = df_display.sort_values('日時', ascending=True)

        table_key = f"reservation_list_table_{st.session_state['list_reset_counter']}"

        event_selection = st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=table_key,
            height="auto",
            column_config={
                "日時": st.column_config.TextColumn("日時", width="medium"),
                "施設": st.column_config.TextColumn("施設", width="medium"),
                "状態": st.column_config.TextColumn("状態", width="small"),
                "参加者": st.column_config.TextColumn("参加者", width="large"),
                "メモ": st.column_config.TextColumn("メモ", width="large"),
            }
        )
        
        if len(event_selection.selection.rows) > 0:
            selected_row_idx = event_selection.selection.rows[0]
            actual_idx = df_display.index[selected_row_idx]
            
            # リストで選択が変わった時
            if st.session_state.get('active_event_idx') != actual_idx:
                st.session_state['active_event_idx'] = actual_idx
                target_date = df_res.loc[actual_idx]["date"]
                st.session_state['clicked_date'] = str(target_date)
                
                # ポップアップON
                st.session_state['is_popup_open'] = True
                st.session_state['popup_mode'] = "edit"
                st.rerun()
    else:
        st.info("表示できる予約データがありません。")


# ==========================================
# 6. イベントハンドリング（★完全解決版）
# ==========================================

# 状態変数の初期化
if 'is_popup_open' not in st.session_state:
    st.session_state['is_popup_open'] = False

if 'last_click_signature' not in st.session_state:
    st.session_state['last_click_signature'] = None

if 'popup_mode' not in st.session_state:
    st.session_state['popup_mode'] = None

if 'prev_cal_state' not in st.session_state:
    st.session_state['prev_cal_state'] = None

if 'active_event_idx' not in st.session_state:
    st.session_state['active_event_idx'] = None

# ★追加: リスト操作直後のカレンダーイベントを無視するためのフラグ
if 'skip_calendar_event' not in st.session_state:
    st.session_state['skip_calendar_event'] = False

if cal_state:
    # 状態が変わった時だけ処理
    if cal_state != st.session_state['prev_cal_state']:
        st.session_state['prev_cal_state'] = cal_state
        
        # ★最優先: リスト操作直後の「カレンダーの更新（エコー）」なら無視して通す
        if st.session_state['skip_calendar_event']:
            st.session_state['skip_calendar_event'] = False
            # 念のため現在のビュー開始日を更新しておく（次回の誤動作防止）
            current_view = cal_state.get("view", {})
            st.session_state['last_view_start'] = current_view.get("currentStart")
            # 何もせず終了（ポップアップは維持される）
        
        else:
            # 通常の判定処理へ
            current_view = cal_state.get("view", {})
            current_start = current_view.get("currentStart")
            
            if 'last_view_start' not in st.session_state:
                st.session_state['last_view_start'] = current_start
            
            # 1. ナビゲーション（月移動）チェック
            if current_start != st.session_state['last_view_start']:
                # 月が変わったら強制リセット
                st.session_state['last_view_start'] = current_start
                st.session_state['is_popup_open'] = False
                st.session_state['active_event_idx'] = None
                st.session_state['list_reset_counter'] += 1
            
            else:
                # 2. クリックチェック
                callback = cal_state.get("callback")
                current_signature = None
                if callback == "dateClick":
                    current_signature = f"date_{cal_state['dateClick']['date']}"
                elif callback == "eventClick":
                    current_signature = f"event_{cal_state['eventClick']['event']['id']}"
                
                # 新しいクリックなら開く
                if current_signature and current_signature != st.session_state['last_click_signature']:
                    st.session_state['last_click_signature'] = current_signature
                    st.session_state['is_popup_open'] = True
                    
                    if callback == "dateClick":
                        st.session_state['clicked_date'] = cal_state["dateClick"]["date"]
                        st.session_state['active_event_idx'] = None
                        st.session_state['popup_mode'] = "new"
                        st.session_state['list_reset_counter'] += 1
                    
                    elif callback == "eventClick":
                        idx = int(cal_state["eventClick"]["event"]["id"])
                        st.session_state['active_event_idx'] = idx
                        if idx in df_res.index:
                            target_date = df_res.loc[idx]["date"]
                            st.session_state['clicked_date'] = str(target_date)
                        st.session_state['popup_mode'] = "edit"
                        st.session_state['list_reset_counter'] += 1
                    
                    st.rerun()


# ==========================================
# 7. ポップアップ画面の定義（閉じるボタン完全版）
# ==========================================
@st.dialog("予約内容の登録・編集")
def entry_form_dialog(mode, idx=None, date_str=None):
    # --- A. 新規登録モード ---
    if mode == "new":
        display_date = to_jst_date(date_str)
        st.write(f"📅 **日付:** {display_date}")
        
        past_facilities = []
        if 'facility' in df_res.columns:
            past_facilities = df_res['facility'].dropna().unique().tolist()
        
        facility_select = st.selectbox("施設名", options=["(施設名を選択)"] + past_facilities + ["新規登録"], index=0)
        facility = st.text_input("施設名を入力") if facility_select == "新規登録" else (facility_select if facility_select != "(施設名を選択)" else "")

        status = st.selectbox("ステータス", ["確保", "抽選中", "中止"], index=1)

        col1, col2 = st.columns(2)
        with col1: start_time = st.time_input("開始時間", value=dt_time(9, 0), step=timedelta(minutes=30))
        with col2: end_time = st.time_input("終了時間", value=dt_time(11, 0), step=timedelta(minutes=30))

        message = st.text_area("メモ", placeholder="例：集合時間や持ち物など")

        st.markdown('<div style="margin-top: -20px;"></div>', unsafe_allow_html=True)
        st.divider()

        col_reg, col_close = st.columns([1, 1])
        with col_reg:
            if st.button("登録する", type="primary", use_container_width=True):
                if facility == "":
                    st.error("⚠️ 施設名を選択してください")
                elif end_time <= start_time:
                    st.error("⚠️ 終了時間は開始時間より後にしてください")
                else:
                    # 施設名をfacilitiesシートに自動追加
                    add_facility_if_not_exists(facility)
                    
                    new_row = {
                        "date": to_jst_date(date_str),
                        "facility": facility,
                        "status": status,
                        "start_hour": start_time.hour,
                        "start_minute": start_time.minute,
                        "end_hour": end_time.hour,
                        "end_minute": end_time.minute,
                        "participants": [],
                        "absent": [],
                        "consider": [],
                        "message": message.replace('\n', '<br>')
                    }
                    current_df = load_reservations()
                    updated_df = pd.concat([current_df, pd.DataFrame([new_row])], ignore_index=True)
                    save_reservations(updated_df)
                    st.session_state['show_success_message'] = '登録しました'
                    st.session_state['is_popup_open'] = False
                    st.session_state['last_click_signature'] = None
                    st.session_state['active_event_idx'] = None
                    st.session_state['list_reset_counter'] += 1
                    st.rerun()
        with col_close:
            if st.button("閉じる", use_container_width=True):
                st.session_state['is_popup_open'] = False
                # ▼この3つがあれば完璧です
                st.session_state['last_click_signature'] = None  # カレンダーの同日再クリック用
                st.session_state['active_event_idx'] = None      # リストの再クリック用
                st.session_state['list_reset_counter'] += 1      # リストの見た目リセット用


                st.rerun()

    # --- B. 編集モード ---
    elif mode == "edit" and idx is not None:
        if idx not in df_res.index:
            st.error("イベントが削除されました。")
            if st.button("閉じる"):
                st.session_state['is_popup_open'] = False
                # ▼この3つがあれば完璧です
                st.session_state['last_click_signature'] = None  # カレンダーの同日再クリック用
                st.session_state['active_event_idx'] = None      # リストの再クリック用
                st.session_state['list_reset_counter'] += 1      # リストの見た目リセット用

                st.rerun()
            return

        r = df_res.loc[idx]
        
        # 施設情報を取得
        facilities_data = load_facilities_data()
        facility_info = facilities_data.get(r['facility'], {})
        facility_url = facility_info.get('url', '')
        facility_address = facility_info.get('address', '')
        
        def clean_join(lst):
            if not isinstance(lst, list): return 'なし'
            valid_names = [str(x) for x in lst if x and str(x).strip() != '']
            return ', '.join(valid_names) if valid_names else 'なし'

        # メモの<br>を改行に変換して表示
        display_msg = r.get('message', '')
        if pd.notna(display_msg) and display_msg:
            display_msg = display_msg.replace('<br>', '\n')
        else:
            display_msg = '（なし）'
        
        st.markdown(f"**日時:** {r['date']} {int(safe_int(r.get('start_hour'))):02}:{int(safe_int(r.get('start_minute'))):02} - {int(safe_int(r.get('end_hour'))):02}:{int(safe_int(r.get('end_minute'))):02}")
        
        # Googleカレンダーに追加リンク
        calendar_url = generate_google_calendar_url(r)
        st.markdown(f'<a href="{calendar_url}" target="_blank" style="font-size: 14px; color: #1f77b4;">カレンダーに追加</a>', unsafe_allow_html=True)
        
        # 施設情報表示
        if facility_url:
            st.markdown(f'**施設:** <a href="{facility_url}" target="_blank" style="color: #1f77b4;">{r["facility"]} </a>', unsafe_allow_html=True)
        else:
            st.markdown(f"**施設:** {r['facility']}")
        
        if facility_address:
            map_url = f"https://www.google.com/maps/search/?api=1&query={quote(facility_address)}"
            st.markdown(f'**住所:** <a href="{map_url}" target="_blank" style="color: #1f77b4;">{facility_address}</a>', unsafe_allow_html=True)
        st.markdown(f"**ステータス:** {r['status']}")
        st.markdown(f"**参加:** {clean_join(r.get('participants'))}")
        st.markdown(f"**保留:** {clean_join(r.get('consider'))}")
        st.markdown(f"**メモ:**\n{display_msg}")
        
        st.markdown('<div style="margin-top: -20px;"></div>', unsafe_allow_html=True)
        st.divider()

        st.subheader("参加表明")
        past_nicks = []
        for col in ["participants", "absent", "consider"]:
            if col in df_res.columns:
                for lst in df_res[col]:
                    if isinstance(lst, list): past_nicks.extend([n for n in lst if n])
                    elif isinstance(lst, str) and lst.strip(): past_nicks.extend(lst.split(";"))
        past_nicks = sorted(set(past_nicks), key=lambda s: s)
        
        col_nick, col_type = st.columns([1, 1])
        with col_nick:
            nick_choice = st.selectbox("名前", options=["(選択)"] + past_nicks + ["新規入力"], key="edit_nick")
            nick = st.text_input("名前を入力", key="edit_nick_input") if nick_choice == "新規入力" else (nick_choice if nick_choice != "(選択)" else "")
        with col_type:
            part_type = st.radio("区分", ["参加", "保留", "削除"], horizontal=True, key="edit_type")

        col_upd, col_close_main = st.columns([1, 1])
        with col_upd:
            if st.button("反映する", type="primary", use_container_width=True):
                if not nick:
                    st.warning("名前を選択してください")
                else:
                    current_df = load_reservations()
                    if idx in current_df.index:
                        participants = list(current_df.at[idx, "participants"]) if isinstance(current_df.at[idx, "participants"], list) else []
                        absent = list(current_df.at[idx, "absent"]) if isinstance(current_df.at[idx, "absent"], list) else []
                        consider = list(current_df.at[idx, "consider"]) if isinstance(current_df.at[idx, "consider"], list) else []

                        if nick in participants: participants.remove(nick)
                        if nick in absent: absent.remove(nick)
                        if nick in consider: consider.remove(nick)

                        if part_type == "参加": participants.append(nick)
                        elif part_type == "保留": consider.append(nick)
                        
                        current_df.at[idx, "participants"] = participants
                        current_df.at[idx, "absent"] = absent
                        current_df.at[idx, "consider"] = consider
                        
                        save_reservations(current_df)
                        st.success("反映しました")
                        st.rerun()
        with col_close_main:
            if st.button("閉じる", use_container_width=True):
                st.session_state['is_popup_open'] = False
                # ▼この3つがあれば完璧です
                st.session_state['last_click_signature'] = None  # カレンダーの同日再クリック用
                st.session_state['active_event_idx'] = None      # リストの再クリック用
                st.session_state['list_reset_counter'] += 1      # リストの見た目リセット用

                st.rerun()

        with st.expander("管理者メニュー（編集・削除）"):
            edit_tab, delete_tab = st.tabs(["内容編集", "削除"])
            with edit_tab:
                new_msg = st.text_area("メモの編集", value=r.get("message", "").replace('<br>', '\n'))
                new_status = st.selectbox("ステータスの変更", ["確保", "抽選中", "中止", "完了"], index=["確保", "抽選中", "中止", "完了"].index(r['status']) if r['status'] in ["確保", "抽選中", "中止", "完了"] else 0)
                
                if st.button("内容を更新", use_container_width=True):
                    current_df = load_reservations()
                    current_df.at[idx, "message"] = new_msg.replace('\n', '<br>')
                    current_df.at[idx, "status"] = new_status
                    save_reservations(current_df)
                    st.success("更新しました")
                    st.rerun()

            with delete_tab:
                st.warning("本当に削除しますか？")
                if st.button("削除実行", type="primary", use_container_width=True):
                    current_df = load_reservations()
                    current_df = current_df.drop(idx).reset_index(drop=True)
                    save_reservations(current_df)
                    st.session_state['show_success_message'] = '削除しました'
                    st.session_state['is_popup_open'] = False
                    st.session_state['last_click_signature'] = None
                    st.session_state['active_event_idx'] = None
                    st.session_state['list_reset_counter'] += 1
                    st.rerun()


# ==========================================
# 8. ポップアップ表示制御
# ==========================================
if st.session_state['is_popup_open']:
    if st.session_state['popup_mode'] == "new":
        d_str = st.session_state.get('clicked_date', str(date.today()))
        entry_form_dialog("new", date_str=d_str)

    elif st.session_state['popup_mode'] == "edit":
        e_idx = st.session_state.get('active_event_idx')
        if e_idx is not None:
            entry_form_dialog("edit", idx=e_idx)