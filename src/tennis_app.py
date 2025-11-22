import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
from streamlit_calendar import calendar
import gspread
from google.oauth2.service_account import Credentials
import json
from google.oauth2 import service_account

# ===== Google Sheets 認証 =====

google_secrets = st.secrets["google"]

@st.cache_resource(show_spinner=False)
def get_gsheet():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]

    creds = Credentials.from_service_account_info(
        dict(google_secrets),
        scopes=scope
    )

    client = gspread.authorize(creds)
    sheetid = "1_l57W7GIx1OR56uaWt8OBZ1_Lbr8GtWwS_QfvqFrKp0"
    worksheet = client.open_by_key(sheetid).sheet1
    return worksheet

worksheet = get_gsheet()


#データ読み込み
records = worksheet.get_all_records()
df = pd.DataFrame(records)

# ===== Google Sheets 読み書き関数 =====
def load_reservations():
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)

    # 期待されるカラムを確実に用意する
    expected_cols = [
        "date","facility","status","start_hour","start_minute",
        "end_hour","end_minute","participants","absent","message"
    ]
    for c in expected_cols:
        if c not in df.columns:
            # 欠けているカラムは空文字で埋める（participants/absent は後でリスト化）
            df[c] = ""

    # 日付パース
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    # 時刻カラムを整数化（文字列や空欄が混在する可能性を吸収）
    for col in ["start_hour", "start_minute", "end_hour", "end_minute"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # participants, absent をリストに変換
    def _to_list_cell(x):
        if isinstance(x, (list, tuple)):
            return list(x)
        if pd.isna(x) or x == "":
            return []
        return str(x).split(";")

    df["participants"] = df["participants"].apply(_to_list_cell)
    df["absent"] = df["absent"].apply(_to_list_cell)

    # message を空文字で埋める
    df["message"] = df["message"].fillna("")

    return df

def save_reservations(df):
    # participants, absent を文字列に変換
    df_to_save = df.copy()
    for col in ["participants", "absent"]:
        if col in df_to_save.columns:
            df_to_save[col] = df_to_save[col].apply(lambda lst: ";".join(lst) if isinstance(lst, (list, tuple)) else (lst if pd.notnull(lst) else ""))

    # date を ISO 文字列に変換しておく
    if "date" in df_to_save.columns:
        df_to_save["date"] = df_to_save["date"].apply(lambda d: d.isoformat() if isinstance(d, (date, datetime, pd.Timestamp)) else (str(d) if pd.notnull(d) else ""))

    # NaN を空文字にし、すべてセルを JSON 互換なプリミティブに変換する
    df_to_save = df_to_save.where(pd.notnull(df_to_save), "")

    def _serialize_cell(v):
        # datetime-like
        if isinstance(v, (date, datetime, pd.Timestamp)):
            return v.isoformat()
        # list/tuple -> join
        if isinstance(v, (list, tuple)):
            return ";".join(map(str, v))
        # primitives
        if isinstance(v, (str, int, float, bool)):
            return v
        # fallback: empty string for NaN/None, else str()
        try:
            if pd.isna(v):
                return ""
        except Exception:
            pass
        return str(v)

    values = [df_to_save.columns.values.tolist()]
    # apply serialization per-cell to ensure JSON-serializable types
    ser_df = df_to_save.applymap(_serialize_cell)
    values += ser_df.values.tolist()

    # Google Sheets にアップデート
    worksheet.clear()
    worksheet.update(values)

# ===== JST変換関数 =====
def to_jst_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (dt + timedelta(hours=9)).date()
    except Exception:
        if isinstance(iso_str, date):
            return iso_str
        return datetime.strptime(str(iso_str)[:10], "%Y-%m-%d").date()


# ===== JST変換 =====
def to_jst_date(iso_str):
    """ISO形式の日付文字列をJSTのdate型に変換"""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (dt + timedelta(hours=9)).date()
    except Exception:
        if isinstance(iso_str, date):
            return iso_str
        return datetime.strptime(str(iso_str)[:10], "%Y-%m-%d").date()
    
# ===== CSSで親要素の高さを自然にする =====
st.markdown("""
<style>

/* ← 最重要：最近の Streamlit はこのセレクタで余白を適用する必要がある */
.stAppViewContainer {
    margin-top: 0.5rem !important;
}

/* これが古いセレクタ。環境によっては効かない */
.stApp {
    padding-top: 0 !important;
}

/* コンテナの上の余白を最小化 */
.block-container {
    padding-top: 2.0rem !important; /* ここでタイトルの位置が変わる必要に応じて調整(小さいと余白が減り上へ行く) */
}

</style>
""", unsafe_allow_html=True)




# ===== タイトル =====

st.markdown("<h3>🎾 テニスコート予約管理</h3>", unsafe_allow_html=True)

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

    start_dt = datetime.combine(r["date"], time(int(r.get("start_hour",0)), int(r.get("start_minute",0))))
    end_dt   = datetime.combine(r["date"], time(int(r.get("end_hour",0)), int(r.get("end_minute",0))))

    color = status_color.get(r["status"], {"bg":"#FFFFFF","text":"black"})

    # タイトルをステータス＋施設名のみにする
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
        "height": "auto",         # ✅ 高さを自動調整（重要）
        "contentHeight": "auto",  # ✅ カレンダー内コンテンツに応じて伸縮
        "aspectRatio": 1.2,       # ✅ 横長になりすぎないよう調整（1.0〜1.5で微調整）
        "titleFormat": {  # ここを追加
            "year": "numeric",
            "month": "2-digit"  # 12 のように2桁で表示
        }
    },
    key="reservation_calendar"
)


# ===== イベント操作 =====
if cal_state:
    callback = cal_state.get("callback")

    # ---- 日付クリック ----
    if callback == "dateClick":
        clicked_date = cal_state["dateClick"]["date"]
        clicked_date_jst = to_jst_date(clicked_date)

        st.session_state['clicked_date'] = clicked_date
        st.session_state['clicked_date_jst'] = clicked_date_jst
    
        # スクロール用のアンカーと自動スクロール
        st.markdown('<div id="form-section"></div>', unsafe_allow_html=True)
        st.markdown("""
        <script>
        document.getElementById('form-section').scrollIntoView({behavior: 'smooth'});
        </script>
        """, unsafe_allow_html=True)
        
        st.info(f"📅 {clicked_date_jst} の予約を確認/登録")

        # ---- 日付クリック時の施設名入力 ----
        # 過去登録済み施設（データが空やカラム未存在の場合に対応）
        if 'facility' in df_res.columns:
            past_facilities = df_res['facility'].dropna().unique().tolist()
        else:
            past_facilities = []
        facility_select = st.selectbox("施名を選択または新規登録(直接入力で検索可能)", options=["(施設名を選択)"] + past_facilities + ["新規登録"], index=0)

        # 新規登録の場合だけ入力欄を表示
        if facility_select == "新規登録":
            facility = st.text_input("施設名を入力")        
        elif facility_select == "(施設名を選択)" or facility_select == "" :
            facility = ""
        else:
            facility = facility_select

        status = st.selectbox("ステータス", ["確保", "抽選中", "中止"], key=f"st_{clicked_date}")

        # --- 時間選択（30分単位 + コンパクト配置 + モバイル調整） ---
        st.markdown("**開始時間**", help="下のスクロールで設定します。")
        st.write("")  # 空行を1つだけ入れて間隔を最小限に
        start_time = st.time_input(
            label="",
            value=time(9, 0),
            key=f"start_{clicked_date}",
            step=timedelta(minutes=30),
            label_visibility="collapsed"
        )

        st.markdown("<div style='margin-top:-10px'></div>", unsafe_allow_html=True)
        st.markdown("**終了時間**")
        st.write("")
        end_time = st.time_input(
            label="",
            value=time(10, 0),
            key=f"end_{clicked_date}",
            step=timedelta(minutes=30),
            label_visibility="collapsed"
        )

        # --- 📝 メッセージ欄を追加 ---
        message_buf = st.text_area(
            "メッセージ（任意）",
            placeholder="例：集合時間や持ち物など",
            key=f"msg_{clicked_date}"
        )
        message = message_buf.replace('\n', '<br>')    



        # --- 登録ボタン ---
        clicked_date = st.session_state.get('clicked_date')
        clicked_date_jst = st.session_state.get('clicked_date_jst')

        if clicked_date is not None:
            if st.button("登録", key=f"reg_{clicked_date}"):
                #もしfacilityが空文字の場合は何もしない
                if facility == "":
                    st.warning("⚠️ 施設名が選択されていません。")
                else:
                    if end_time <= start_time:
                        st.warning("⚠️ 終了時間は開始時間より後にしてください。")
                    else:
                        df_res = pd.concat([df_res, pd.DataFrame([{
                            "date": clicked_date_jst,
                            "facility": facility,
                            "status": status,
                            "start_hour": start_time.hour,
                            "start_minute": start_time.minute,
                            "end_hour": end_time.hour,
                            "end_minute": end_time.minute,
                            "participants": [],
                            "absent": [],
                            "message": message
                        }])], ignore_index=True)
                        save_reservations(df_res)
                        st.success(f"{clicked_date_jst} に {facility} を登録しました")
                        st.rerun()


# ---- イベントクリック ----
    elif callback == "eventClick":
        ev = cal_state["eventClick"]["event"]
        idx = int(ev["id"])
        
        # スクロール用のアンカーと自動スクロール
        st.markdown('<div id="form-section"></div>', unsafe_allow_html=True)
        st.markdown("""
        <script>
        document.getElementById('form-section').scrollIntoView({behavior: 'smooth'});
        </script>
        """, unsafe_allow_html=True)
        
        if idx not in df_res.index:
            st.warning("このイベントは存在しません。")
        else:
            r = df_res.loc[idx]
            event_date = to_jst_date(r["date"])

            # 詳細表示（改行対応）
            st.markdown(f"""
            ### イベント詳細
            日付: {event_date}<br>
            施設: {r['facility']}<br>
            ステータス: {r['status']}<br>
            時間:<br> &nbsp;&nbsp;{int(r['start_hour']):02d}:{int(r['start_minute']):02d} - {int(r['end_hour']):02d}:{int(r['end_minute']):02d}<br>
            参加者:<br> &nbsp;&nbsp;{', '.join(r['participants']) if r['participants'] else 'なし'}<br>
            不参加者:<br> &nbsp;&nbsp;{', '.join(r['absent']) if r['absent'] else 'なし'}<br>
            メッセージ:<br> &nbsp;&nbsp;{r['message'] if pd.notna(r.get('message')) and r['message'] else '（なし）'}

            """, unsafe_allow_html=True)

            # 施設名選択（過去登録から選択可）
            # 過去登録済み施設（データが空やカラム未存在の場合に対応）
            if 'facility' in df_res.columns:
                past_facilities = df_res['facility'].dropna().unique().tolist()
            else:
                past_facilities = []

            # ---- ニックネーム入力 ----
            past_nicks = []
            for col in ["participants", "absent"]:
                if col in df_res.columns:
                    for lst in df_res[col]:
                        if isinstance(lst, list):
                            past_nicks.extend([n for n in lst if n])
                        elif isinstance(lst, str) and lst.strip():
                            past_nicks.extend(lst.split(";"))

            # 一意化 & 五十音順
            past_nicks = sorted(set(past_nicks), key=lambda s: s)

            # 選択肢 + 新規入力をまとめて一箇所で表示
            nick_choice = st.selectbox("ニックネーム選択または新規登録(文字入力で検索可能)",
                                    options=["(ニックネーム選択)"] + past_nicks + ["新規登録"], key=f"nick_choice_{idx}")

            if nick_choice == "新規登録":
                nick = st.text_input("新しいニックネーム入力", key=f"nick_input_{idx}")
            elif nick_choice == "(入力/選択)":
                nick = ""
            else:
                nick = nick_choice
        

            # 新規登録の場合だけ入力欄を表示
            # 参加状況
            part = st.radio("参加状況", ["参加", "不参加", "削除"], key=f"part_{idx}")

            if st.button("反映", key=f"apply_{idx}"):
                if not nick:
                    st.warning("⚠️ ニックネームが選択されていません。")
                else:
                    participants = list(r["participants"]) if isinstance(r["participants"], list) else []
                    absent = list(r["absent"]) if isinstance(r["absent"], list) else []

                    # まず既存から削除
                    if nick in participants: participants.remove(nick)
                    if nick in absent: absent.remove(nick)

                    # 反映
                    if part == "参加":
                        participants.append(nick)
                    elif part == "不参加":
                        absent.append(nick)
                    # 削除は既に削除済み

                    df_res.at[idx, "participants"] = participants
                    df_res.at[idx, "absent"] = absent
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