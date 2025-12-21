import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
# ★重要: 時間を扱うクラスを 'dt_time' という別名にして、下の time モジュールと区別する
from datetime import time as dt_time  
from streamlit_calendar import calendar
import gspread
from google.oauth2.service_account import Credentials
import json
import time  # ★重要: API待機用のモジュール（こちらを 'time' として使う）
from gspread.exceptions import APIError

# ==========================================
# 1. 共通関数・設定 (高速化・安定化用)
# ==========================================

# API制限対策: エラーが出たら少し待って再試行する関数
def run_with_retry(func, *args, **kwargs):
    """
    func: 実行したい関数オブジェクト（()をつけずに渡すこと）
    """
    max_retries = 5
    for i in range(max_retries):
        try:
            # ここで関数を実行
            return func(*args, **kwargs)
        except APIError as e:
            if i == max_retries - 1: raise e
            code = e.response.status_code
            if code == 429 or code >= 500:
                time.sleep(2 ** (i + 1)) # timeモジュールで待機
            else:
                raise e
        except Exception as e:
            if i == max_retries - 1: raise e
            time.sleep(2)

# 安全な数値変換
def safe_int(val, default=0):
    try:
        if pd.isna(val) or val == "": return default
        return int(float(val))
    except:
        return default

# JST変換関数
def to_jst_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (dt + timedelta(hours=9)).date()
    except Exception:
        if isinstance(iso_str, date): return iso_str
        return datetime.strptime(str(iso_str)[:10], "%Y-%m-%d").date()


# ===== Google Sheets 認証 =====
GSHEET_ID = st.secrets.get("google", {}).get("GSHEET_ID")
if not GSHEET_ID:
    st.error("Secretsの設定エラー: [google] セクション内に GSHEET_ID が見つかりません。")
    st.stop()

# 接続用キャッシュ
@st.cache_resource(show_spinner=False)
def get_gsheet(sheet_id, sheet_name):
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    service_account_info = dict(st.secrets["google"])
    creds = Credentials.from_service_account_info(service_account_info, scopes=scope)
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(sheet_id).worksheet(sheet_name)
    return worksheet

# メインシート接続
try:
    worksheet = get_gsheet(GSHEET_ID, "reservations")
except Exception as e:
    st.error(f"Google Sheetへの接続に失敗しました: {e}")
    st.stop()


# ==========================================
# 2. データ読み書き（高速化対応）
# ==========================================

# ★高速化: 15秒間キャッシュ
@st.cache_data(ttl=15)
def load_reservations():
    # リトライ経由で取得（()をつけずに渡す）
    data = run_with_retry(worksheet.get_all_records)
    df = pd.DataFrame(data)

    expected_cols = [
        "date","facility","status","start_hour","start_minute",
        "end_hour","end_minute","participants","absent","consider","message"
    ]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = ""

    # 日付パース
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    # リスト変換
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
    
    # リスト→文字列
    for col in ["participants", "absent", "consider"]:
        if col in df_to_save.columns:
            df_to_save[col] = df_to_save[col].apply(lambda lst: ";".join(lst) if isinstance(lst, (list, tuple)) else (lst if pd.notnull(lst) else ""))

    # 日付→ISO文字列
    if "date" in df_to_save.columns:
        df_to_save["date"] = df_to_save["date"].apply(lambda d: d.isoformat() if isinstance(d, (date, datetime, pd.Timestamp)) else (str(d) if pd.notnull(d) else ""))

    # NaN削除
    df_to_save = df_to_save.where(pd.notnull(df_to_save), "")

    def _serialize_cell(v):
        if isinstance(v, (date, datetime, pd.Timestamp)): return v.isoformat()
        if isinstance(v, (list, tuple)): return ";".join(map(str, v))
        return str(v)

    values = [df_to_save.columns.values.tolist()]
    ser_df = df_to_save.map(_serialize_cell)
    values += ser_df.values.tolist()

    # ★リトライ経由で書き込み & キャッシュクリア
    run_with_retry(worksheet.clear)
    run_with_retry(worksheet.update, values)
    load_reservations.clear()


# ==========================================
# 3. 抽選リマインダー (v2.0)
# ==========================================
def check_and_show_reminders():
    try:
        try:
            lottery_sheet = get_gsheet(GSHEET_ID, "lottery_periods")
        except Exception:
            return

        # リトライ経由で取得
        records = run_with_retry(lottery_sheet.get_all_records)
        df = pd.DataFrame(records)
        if df.empty: return

        jst_now = datetime.utcnow() + timedelta(hours=9)
        today = jst_now.date()
        current_day = today.day
        current_weekday = today.strftime("%a")

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
                    if s_day <= current_day <= e_day: is_match = True
                elif freq == "weekly":
                    if current_weekday in str(row.get("weekdays", "")): is_match = True
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

        if messages_to_show:
            for m in messages_to_show:
                st.info(f"🔔 {m}", icon=None)
    except Exception as e:
        print(f"Reminder Error: {e}")


# ==========================================
# 4. 画面描画
# ==========================================
st.markdown("""
<style>
.stAppViewContainer { margin-top: 0.5rem !important; }
.stApp { padding-top: 0 !important; }
.block-container { padding-top: 2.0rem !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h3>🎾 テニスコート予約管理</h3>", unsafe_allow_html=True)

check_and_show_reminders()

df_res = load_reservations()

status_color = {
    "確保": {"bg":"#90ee90","text":"black"},
    "抽選中": {"bg":"#ffd966","text":"black"},
    "中止": {"bg":"#d3d3d3","text":"black"},
    "完了": {"bg":"#d3d3d3","text":"black"}
}

events = []
for idx, r in df_res.iterrows():
    # 日付データの安全な取り出し
    raw_date = r.get("date")
    if pd.isna(raw_date) or raw_date == "": continue
    
    # 型チェック強化
    if isinstance(raw_date, str):
        try: curr_date = datetime.fromisoformat(str(raw_date)[:10]).date()
        except: continue
    else:
        curr_date = raw_date

    # 時間データの安全な取り出し
    s_hour = safe_int(r.get("start_hour"), 9)
    s_min  = safe_int(r.get("start_minute"), 0)
    e_hour = safe_int(r.get("end_hour"), 11)
    e_min  = safe_int(r.get("end_minute"), 0)

    try:
        # ★重要: ここで dt_time を使用 (time だとエラーになります)
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


cal_state = calendar(
    events=events,
    options={
        "initialView": "dayGridMonth",
        "selectable": True,
        "headerToolbar": {"left": "prev,next today", "center": "title", "right": ""},
        "eventDisplay": "block",
        "displayEventTime": False,
        "height": "auto",
        "contentHeight": "auto",
        "aspectRatio": 1.2,
        "titleFormat": {"year": "numeric", "month": "2-digit"}
    },
    key="reservation_calendar"
)


if cal_state:
    callback = cal_state.get("callback")

    # ---- 新規登録 ----
    if callback == "dateClick":
        clicked_date = cal_state["dateClick"]["date"]
        clicked_date_jst = to_jst_date(clicked_date)

        st.session_state['clicked_date'] = clicked_date
        st.session_state['clicked_date_jst'] = clicked_date_jst
    
        st.markdown('<div id="form-section"></div>', unsafe_allow_html=True)
        st.markdown("""<script>document.getElementById('form-section').scrollIntoView({behavior: 'smooth'});</script>""", unsafe_allow_html=True)
        
        st.info(f"📅 {clicked_date_jst} の予約を確認/登録")

        past_facilities = []
        if 'facility' in df_res.columns:
            past_facilities = df_res['facility'].dropna().unique().tolist()
        
        facility_select = st.selectbox(
            "施設名を選択または新規登録", 
            options=["(施設名を選択)"] + past_facilities + ["新規登録"], 
            index=0
        )

        facility = ""
        if facility_select == "新規登録":
            facility = st.text_input("施設名を入力")        
        elif facility_select != "(施設名を選択)" and facility_select != "":
            facility = facility_select

        status = st.selectbox("ステータス", ["確保", "抽選中", "中止"], key=f"st_{clicked_date}")

        st.markdown("**開始時間**")
        # ★重要: ここも dt_time を使用
        start_time = st.time_input("", value=dt_time(9, 0), key=f"start_{clicked_date}", step=timedelta(minutes=30), label_visibility="collapsed")
        
        st.markdown("<div style='margin-top:-10px'></div>", unsafe_allow_html=True)
        st.markdown("**終了時間**")
        end_time = st.time_input("", value=dt_time(10, 0), key=f"end_{clicked_date}", step=timedelta(minutes=30), label_visibility="collapsed")

        message_buf = st.text_area("メッセージ（任意）", placeholder="例：集合時間や持ち物など", key=f"msg_{clicked_date}")
        message = message_buf.replace('\n', '<br>')    

        clicked_date = st.session_state.get('clicked_date')
        clicked_date_jst = st.session_state.get('clicked_date_jst')

        if clicked_date is not None:
            if st.button("登録", key=f"reg_{clicked_date}"):
                if facility == "":
                    st.warning("⚠️ 施設名が選択されていません。")
                elif end_time <= start_time:
                    st.warning("⚠️ 終了時間は開始時間より後にしてください。")
                else:
                    new_row = {
                        "date": clicked_date_jst,
                        "facility": facility,
                        "status": status,
                        "start_hour": start_time.hour,
                        "start_minute": start_time.minute,
                        "end_hour": end_time.hour,
                        "end_minute": end_time.minute,
                        "participants": [],
                        "absent": [],
                        "consider": [],
                        "message": message
                    }
                    df_res = pd.concat([df_res, pd.DataFrame([new_row])], ignore_index=True)
                    save_reservations(df_res)
                    st.success(f"{clicked_date_jst} に {facility} を登録しました")
                    st.rerun()


    # ---- 詳細・参加表明 ----
    elif callback == "eventClick":
        ev = cal_state["eventClick"]["event"]
        idx = int(ev["id"])
        
        st.markdown('<div id="form-section"></div>', unsafe_allow_html=True)
        st.markdown("""<script>document.getElementById('form-section').scrollIntoView({behavior: 'smooth'});</script>""", unsafe_allow_html=True)
        
        if idx not in df_res.index:
            st.warning("このイベントは存在しません。")
        else:
            r = df_res.loc[idx]
            event_date = to_jst_date(r["date"])

            st.markdown(f"""
            ### イベント詳細
            日付: {event_date}<br>
            施設: {r['facility']}<br>
            ステータス: {r['status']}<br>
            時間:<br> &nbsp;&nbsp;{int(safe_int(r['start_hour'])):02d}:{int(safe_int(r['start_minute'])):02d} - {int(safe_int(r['end_hour'])):02d}:{int(safe_int(r['end_minute'])):02d}<br>
            参加者:<br> &nbsp;&nbsp;{', '.join(r['participants']) if r['participants'] else 'なし'}<br>
            保留:<br> &nbsp;&nbsp;{', '.join(r['consider']) if 'consider' in r and r['consider'] else 'なし'}<br>
            メッセージ:<br> &nbsp;&nbsp;{r['message'] if pd.notna(r.get('message')) and r['message'] else '（なし）'}
            """, unsafe_allow_html=True)

            past_nicks = []
            for col in ["participants", "absent", "consider"]:
                if col in df_res.columns:
                    for lst in df_res[col]:
                        if isinstance(lst, list): past_nicks.extend([n for n in lst if n])
                        elif isinstance(lst, str) and lst.strip(): past_nicks.extend(lst.split(";"))
            past_nicks = sorted(set(past_nicks), key=lambda s: s)
            
            default_option = "(ニックネーム選択または入力)"
            nick_choice = st.selectbox("ニックネーム選択または新規登録", options=[default_option] + past_nicks + ["新規登録"], key=f"nick_choice_{idx}")

            nick = ""
            if nick_choice == "新規登録":
                nick = st.text_input("新しいニックネーム入力", key=f"nick_input_{idx}")
            elif nick_choice != default_option:
                nick = nick_choice
        
            part = st.radio("参加状況", ["参加", "保留", "削除"], key=f"part_{idx}")

            if st.button("反映", key=f"apply_{idx}"):
                if not nick:
                    st.warning("⚠️ ニックネームが選択されていません。")
                else:
                    participants = list(r["participants"]) if isinstance(r["participants"], list) else []
                    absent = list(r["absent"]) if isinstance(r["absent"], list) else []
                    consider = list(r["consider"]) if "consider" in r and isinstance(r["consider"], list) else []

                    if nick in participants: participants.remove(nick)
                    if nick in absent: absent.remove(nick)
                    if nick in consider: consider.remove(nick)

                    if part == "参加": participants.append(nick)
                    elif part == "保留": consider.append(nick)

                    df_res.at[idx, "participants"] = participants
                    df_res.at[idx, "absent"] = absent
                    df_res.at[idx, "consider"] = consider
                    
                    save_reservations(df_res)
                    st.success(f"{nick} は {part} に設定されました")
                    st.rerun()

            st.markdown("---")
            st.subheader("イベント操作")
            operation = st.radio("操作を選択", ["ステータス変更", "メッセージ変更","削除"], key=f"ev_op_{idx}")

            if operation == "ステータス変更":
                new_status = st.selectbox("新しいステータス", ["確保", "抽選中", "中止", "完了"], key=f"status_change_{idx}")
                if st.button("変更を反映", key=f"apply_status_{idx}"):
                    df_res.at[idx, "status"] = new_status
                    save_reservations(df_res)
                    st.success("ステータスを変更しました")
                    st.rerun()

            elif operation == "削除":
                st.warning("⚠️ 削除確認")
                if st.checkbox("本当に削除しますか？", key=f"confirm_del_{idx}"):
                    if st.button("削除を確定", key=f"delete_{idx}"):
                        df_res = df_res.drop(idx).reset_index(drop=True)
                        save_reservations(df_res)
                        st.success("削除しました")
                        st.rerun()

            elif operation == "メッセージ変更":
                new_message = st.text_area("メッセージ", value=r.get("message", "").replace('<br>', '\n'), key=f"message_change_{idx}", height=100)
                if st.button("変更を反映", key=f"apply_message_{idx}"):
                    df_res.at[idx, "message"] = new_message.replace('\n', '<br>')   
                    save_reservations(df_res)
                    st.success("メッセージを変更しました")
                    st.rerun()