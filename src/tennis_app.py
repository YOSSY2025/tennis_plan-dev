import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
from streamlit_calendar import calendar
import gspread
from google.oauth2.service_account import Credentials
import json

# ===== Google Sheets 認証 =====
GSHEET_ID = st.secrets.get("google", {}).get("GSHEET_ID")
if not GSHEET_ID:
    st.error("Secretsの設定エラー: [google] セクション内に GSHEET_ID が見つかりません。")
    st.stop()

# キャッシュ設定: sheet_idを引数にしてリロード対応
@st.cache_resource(show_spinner=False)
def get_gsheet(sheet_id):
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    service_account_info = dict(st.secrets["google"])
    creds = Credentials.from_service_account_info(
        service_account_info,
        scopes=scope
    )
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(sheet_id).worksheet("reservations")
    return worksheet

try:
    worksheet = get_gsheet(GSHEET_ID)
except Exception as e:
    st.error(f"Google Sheetへの接続に失敗しました: {e}")
    st.stop()


# ===== Google Sheets 読み書き関数 =====
def load_reservations():
    # 常に最新を取得
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)

    # 期待されるカラム（consider を含む）
    expected_cols = [
        "date","facility","status","start_hour","start_minute",
        "end_hour","end_minute","participants","absent","consider","message"
    ]
    for c in expected_cols:
        if c not in df.columns:
            # カラムがなければ空文字で作成
            df[c] = ""

    # 日付パース
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    # 時刻カラムを整数化
    for col in ["start_hour", "start_minute", "end_hour", "end_minute"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # リスト変換ヘルパー
    def _to_list_cell(x):
        if isinstance(x, (list, tuple)):
            return list(x)
        if pd.isna(x) or x == "":
            return []
        return str(x).split(";")

    # participants, absent, consider をそれぞれリスト化
    for col in ["participants", "absent", "consider"]:
        df[col] = df[col].apply(_to_list_cell)

    # message を空文字で埋める
    df["message"] = df["message"].fillna("")

    return df

def save_reservations(df):
    df_to_save = df.copy()
    
    # 3つのリストカラムを文字列(セミコロン区切り)に変換
    for col in ["participants", "absent", "consider"]:
        if col in df_to_save.columns:
            df_to_save[col] = df_to_save[col].apply(lambda lst: ";".join(lst) if isinstance(lst, (list, tuple)) else (lst if pd.notnull(lst) else ""))

    # date を ISO 文字列に変換
    if "date" in df_to_save.columns:
        df_to_save["date"] = df_to_save["date"].apply(lambda d: d.isoformat() if isinstance(d, (date, datetime, pd.Timestamp)) else (str(d) if pd.notnull(d) else ""))

    # NaN を空文字にし、すべてセルを文字列化して保存
    df_to_save = df_to_save.where(pd.notnull(df_to_save), "")

    def _serialize_cell(v):
        if isinstance(v, (date, datetime, pd.Timestamp)):
            return v.isoformat()
        if isinstance(v, (list, tuple)):
            return ";".join(map(str, v))
        return str(v)

    # ヘッダーとデータを準備
    values = [df_to_save.columns.values.tolist()]
    ser_df = df_to_save.map(_serialize_cell)
    values += ser_df.values.tolist()

    # Google Sheets にアップデート（全書き換え）
    worksheet.clear()
    worksheet.update(values)

# ===== JST変換関数 =====
def to_jst_date(iso_str):
    """ISO形式の日付文字列をJSTのdate型に変換"""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (dt + timedelta(hours=9)).date()
    except Exception:
        if isinstance(iso_str, date):
            return iso_str
        return datetime.strptime(str(iso_str)[:10], "%Y-%m-%d").date()

# ===== 抽選リマインダー機能 (v2.0) =====
def check_and_show_reminders():
    """
    lottery_periods シートを読み込み、今日が期間内であればメッセージを表示する
    columns: id, title, frequency, start_month, start_day, end_month, end_day, weekdays, messages, enabled
    """
    try:
        # シート接続（キャッシュせず毎回チェック、または短時間キャッシュ）
        # ※頻繁な変更がないなら @st.cache_data(ttl=600) とかでも良い
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        service_account_info = dict(st.secrets["google"])
        creds = Credentials.from_service_account_info(service_account_info, scopes=scope)
        client = gspread.authorize(creds)
        
        sheet_id = st.secrets.get("google", {}).get("GSHEET_ID")
        
        # シートが存在しない場合のハンドリング
        try:
            lottery_sheet = client.open_by_key(sheet_id).worksheet("lottery_periods")
        except gspread.WorksheetNotFound:
            # シートがまだなければ何もしない
            return

        records = lottery_sheet.get_all_records()
        df = pd.DataFrame(records)
        
        if df.empty:
            return

        # JSTで現在日時を取得
        jst_now = datetime.utcnow() + timedelta(hours=9)
        today = jst_now.date()
        current_month = today.month
        current_day = today.day
        current_weekday = today.strftime("%a") # Mon, Tue, ...

        messages_to_show = []

        for _, row in df.iterrows():
            # 1. 有効フラグチェック (TRUE, true, 1, などの場合有効)
            enabled_val = str(row.get("enabled", "")).lower()
            if enabled_val not in ["true", "1", "yes", "有効"]:
                continue

            freq = row.get("frequency", "")
            msg = row.get("messages", "")
            if not msg:
                continue

            is_match = False
            
            try:
                # --- 毎月 (monthly) ---
                if freq == "monthly":
                    s_day = int(row.get("start_day", 0))
                    e_day = int(row.get("end_day", 32))
                    # 日付が範囲内か
                    if s_day <= current_day <= e_day:
                        is_match = True

                # --- 毎週 (weekly) ---
                elif freq == "weekly":
                    # "Mon,Thu" のような文字列を想定
                    target_wds = str(row.get("weekdays", ""))
                    if current_weekday in target_wds:
                        is_match = True

                # --- 毎年 (yearly) ---
                elif freq == "yearly":
                    s_month = int(row.get("start_month", 0))
                    s_day = int(row.get("start_day", 0))
                    e_month = int(row.get("end_month", 0))
                    e_day = int(row.get("end_day", 0))

                    if s_month > 0 and e_month > 0:
                        # 期間開始日と終了日を datetime オブジェクト（年は現在）で比較用に作成
                        start_date = date(today.year, s_month, s_day)
                        end_date = date(today.year, e_month, e_day)

                        # 年をまたぐ場合（例: 12月〜1月）の対応
                        if start_date > end_date:
                            # 今日が「開始日以降」または「終了日以前」ならOK
                            if today >= start_date or today <= end_date:
                                is_match = True
                        else:
                            # 通常の期間（例: 5月〜6月）
                            if start_date <= today <= end_date:
                                is_match = True

            except Exception as e:
                # データ変換エラー等はスキップ
                print(f"Reminder Check Error row: {e}")
                continue

            if is_match:
                messages_to_show.append(msg)

        # メッセージ表示
        if messages_to_show:
            for m in messages_to_show:
                # 目立つように info または warning で表示
                st.info(f"🔔{m}", icon=None)

    except Exception as e:
        print(f"Reminder Error: {e}")


# ===== CSS設定 =====
st.markdown("""
<style>
.stAppViewContainer { margin-top: 0.5rem !important; }
.stApp { padding-top: 0 !important; }
.block-container { padding-top: 2.0rem !important; }
</style>
""", unsafe_allow_html=True)


# ===== タイトル =====
st.markdown("<h3>🎾 テニスコート予約管理</h3>", unsafe_allow_html=True)

# リマインダー表示を実行
check_and_show_reminders()

# ===== データ読み込み =====
df_res = load_reservations()

# ===== カレンダーイベント生成 =====
status_color = {
    "確保": {"bg":"#90ee90","text":"black"},
    "抽選中": {"bg":"#ffd966","text":"black"},
    "中止": {"bg":"#d3d3d3","text":"black"},
    "完了": {"bg":"#d3d3d3","text":"black"}
}

events = []
for idx, r in df_res.iterrows():
    if pd.isna(r["date"]):
        continue

    # 時間計算
    start_dt = datetime.combine(r["date"], time(int(r.get("start_hour",0)), int(r.get("start_minute",0))))
    end_dt   = datetime.combine(r["date"], time(int(r.get("end_hour",0)), int(r.get("end_minute",0))))

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


# ===== カレンダー表示 =====
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


# ===== イベント操作 =====
if cal_state:
    callback = cal_state.get("callback")

    # ---- 日付クリック（新規登録） ----
    if callback == "dateClick":
        clicked_date = cal_state["dateClick"]["date"]
        clicked_date_jst = to_jst_date(clicked_date)

        st.session_state['clicked_date'] = clicked_date
        st.session_state['clicked_date_jst'] = clicked_date_jst
    
        # スクロール
        st.markdown('<div id="form-section"></div>', unsafe_allow_html=True)
        st.markdown("""<script>document.getElementById('form-section').scrollIntoView({behavior: 'smooth'});</script>""", unsafe_allow_html=True)
        
        st.info(f"📅 {clicked_date_jst} の予約を確認/登録")

        # 施設名選択肢作成
        if 'facility' in df_res.columns:
            past_facilities = df_res['facility'].dropna().unique().tolist()
        else:
            past_facilities = []
        
        facility_select = st.selectbox(
            "施設名を選択または新規登録", 
            options=["(施設名を選択)"] + past_facilities + ["新規登録"], 
            index=0
        )

        if facility_select == "新規登録":
            facility = st.text_input("施設名を入力")        
        elif facility_select == "(施設名を選択)" or facility_select == "" :
            facility = ""
        else:
            facility = facility_select

        status = st.selectbox("ステータス", ["確保", "抽選中", "中止"], key=f"st_{clicked_date}")

        # --- 時間選択 ---
        st.markdown("**開始時間**")
        start_time = st.time_input("", value=time(9, 0), key=f"start_{clicked_date}", step=timedelta(minutes=30), label_visibility="collapsed")
        
        st.markdown("<div style='margin-top:-10px'></div>", unsafe_allow_html=True)
        st.markdown("**終了時間**")
        end_time = st.time_input("", value=time(10, 0), key=f"end_{clicked_date}", step=timedelta(minutes=30), label_visibility="collapsed")

        # --- メッセージ ---
        message_buf = st.text_area("メッセージ（任意）", placeholder="例：集合時間や持ち物など", key=f"msg_{clicked_date}")
        message = message_buf.replace('\n', '<br>')    

        # --- 登録ボタン ---
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
                        "consider": [], # 新規登録なので空リスト
                        "message": message
                    }
                    df_res = pd.concat([df_res, pd.DataFrame([new_row])], ignore_index=True)
                    save_reservations(df_res)
                    st.success(f"{clicked_date_jst} に {facility} を登録しました")
                    st.rerun()


    # ---- イベントクリック（詳細・参加表明） ----
    elif callback == "eventClick":
        ev = cal_state["eventClick"]["event"]
        idx = int(ev["id"])
        
        # スクロール
        st.markdown('<div id="form-section"></div>', unsafe_allow_html=True)
        st.markdown("""<script>document.getElementById('form-section').scrollIntoView({behavior: 'smooth'});</script>""", unsafe_allow_html=True)
        
        if idx not in df_res.index:
            st.warning("このイベントは存在しません。")
        else:
            r = df_res.loc[idx]
            event_date = to_jst_date(r["date"])

            # 詳細表示に「保留」を追加
            st.markdown(f"""
            ### イベント詳細
            日付: {event_date}<br>
            施設: {r['facility']}<br>
            ステータス: {r['status']}<br>
            時間:<br> &nbsp;&nbsp;{int(r['start_hour']):02d}:{int(r['start_minute']):02d} - {int(r['end_hour']):02d}:{int(r['end_minute']):02d}<br>
            参加者:<br> &nbsp;&nbsp;{', '.join(r['participants']) if r['participants'] else 'なし'}<br>
            不参加:<br> &nbsp;&nbsp;{', '.join(r['absent']) if r['absent'] else 'なし'}<br>
            保留:<br> &nbsp;&nbsp;{', '.join(r['consider']) if 'consider' in r and r['consider'] else 'なし'}<br>
            メッセージ:<br> &nbsp;&nbsp;{r['message'] if pd.notna(r.get('message')) and r['message'] else '（なし）'}
            """, unsafe_allow_html=True)

            # ---- ニックネーム入力 ----
            past_nicks = []
            # 参加・不参加・保留 の全リストからニックネーム履歴を取得
            for col in ["participants", "absent", "consider"]:
                if col in df_res.columns:
                    for lst in df_res[col]:
                        if isinstance(lst, list):
                            past_nicks.extend([n for n in lst if n])
                        elif isinstance(lst, str) and lst.strip():
                            past_nicks.extend(lst.split(";"))

            past_nicks = sorted(set(past_nicks), key=lambda s: s)
            
            default_option = "(ニックネーム選択または入力)"
            
            nick_choice = st.selectbox("ニックネーム選択または新規登録",
                                    options=[default_option] + past_nicks + ["新規登録"], 
                                    key=f"nick_choice_{idx}")

            if nick_choice == "新規登録":
                nick = st.text_input("新しいニックネーム入力", key=f"nick_input_{idx}")
            elif nick_choice == default_option:
                nick = ""
            else:
                nick = nick_choice
        
            # ラジオボタンに「保留」を追加
            part = st.radio("参加状況", ["参加", "不参加", "保留", "削除"], key=f"part_{idx}")

            if st.button("反映", key=f"apply_{idx}"):
                if not nick:
                    st.warning("⚠️ ニックネームが選択されていません。")
                else:
                    # データ取得（なければ空）
                    participants = list(r["participants"]) if isinstance(r["participants"], list) else []
                    absent = list(r["absent"]) if isinstance(r["absent"], list) else []
                    consider = list(r["consider"]) if "consider" in r and isinstance(r["consider"], list) else []

                    # 1. 既存リストから削除（重複防止）
                    if nick in participants: participants.remove(nick)
                    if nick in absent: absent.remove(nick)
                    if nick in consider: consider.remove(nick)

                    # 2. 選択されたリストへ追加
                    if part == "参加":
                        participants.append(nick)
                    elif part == "不参加":
                        absent.append(nick)
                    elif part == "保留":
                        consider.append(nick)
                    # 削除の場合は何もしない

                    # 3. データフレーム更新
                    df_res.at[idx, "participants"] = participants
                    df_res.at[idx, "absent"] = absent
                    df_res.at[idx, "consider"] = consider
                    
                    save_reservations(df_res)
                    st.success(f"{nick} は {part} に設定されました")
                    st.rerun()

            # イベント操作
            st.markdown("---")
            st.subheader("イベント操作")
            operation = st.radio(
                "操作を選択",
                ["ステータス変更", "メッセージ変更","削除"],
                key=f"ev_op_{idx}"
            )

            if operation == "ステータス変更":
                new_status = st.selectbox(
                    "新しいステータス",
                    ["確保", "抽選中", "中止", "完了"],
                    key=f"status_change_{idx}"
                )
                if st.button("変更を反映", key=f"apply_status_{idx}"):
                    df_res.at[idx, "status"] = new_status
                    save_reservations(df_res)
                    st.success(f"イベントのステータスを {new_status} に変更しました")
                    st.rerun()

            elif operation == "削除":
                st.warning("⚠️ このイベントを削除しようとしています。")
                confirm_delete = st.checkbox("本当に削除しますか？", key=f"confirm_del_{idx}")
                if confirm_delete:
                    if st.button("削除を確定", key=f"delete_{idx}"):
                        df_res = df_res.drop(idx).reset_index(drop=True)
                        save_reservations(df_res)
                        st.success("イベントを削除しました")
                        st.rerun()

            elif operation == "メッセージ変更":
                new_message = st.text_area(
                    "メッセージを入力",
                    value=r.get("message", "").replace('<br>', '\n'),
                    key=f"message_change_{idx}",
                    height=100
                )
                if st.button("変更を反映", key=f"apply_message_{idx}"):
                    df_res.at[idx, "message"] = new_message.replace('\n', '<br>')   
                    save_reservations(df_res)
                    st.success("イベントのメッセージを変更しました")
                    st.rerun()