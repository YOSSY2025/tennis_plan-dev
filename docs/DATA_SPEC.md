
# 📘 DATA_SPEC.md

**テニスコート予約アプリ — データ仕様書（更新日：2025/11/16）**

---

# ■ データ保管場所

* **Google Drive** を利用（アプリからAPI連携して読み書き）
* 各データは Google スプレッドシートで管理
* ローカルCSVは現在使用しない

---

# ■ Google Drive API 連携概要

* OAuth2 認証によりアプリからDriveへアクセス
* 読み取り：Google Sheets API によりデータ取得
* 書き込み：追加・更新・削除をAPI経由で反映
* 必要ファイル：
  * `reservations` シート
  * `lottery_periods` シート

※ 認証設定やスクリプトIDは別途「DEVELOPER_SETUP.md」で管理。

---

# ■ reservations シート仕様（予約データ）

| カラム名         | 型       | 内容                             |
| ---------------- | -------- | -------------------------------- |
| id               | string   | 一意の予約ID（UUID）             |
| date             | date     | 予約日（年-月-日）               |
| time             | datetime | 開始日時                         |
| end_time         | datetime | 終了日時                         |
| location         | string   | 施設名                           |
| participants_yes | integer  | 参加者数                         |
| participants_no  | integer  | 不参加者数                       |
| created_by       | string   | 登録者ニックネーム               |
| created_at       | datetime | 登録日時                         |
| status           | string   | 状態（確保／抽選中／中止／完了） |

### ■ 運用ルール

1. アプリ起動時に Drive 上のシートを読み込み
2. 新規登録・更新・削除時に即時API反映
3. 日付経過で自動的に status="完了" に更新
4. 削除時は確認ダイアログ表示

---

# ■ lottery_periods シート仕様（リマインド用データ）

| カラム名    | 型        | 内容・説明                                    |
| ----------- | --------- | --------------------------------------------- |
| id          | string    | UUID                                          |
| title       | string    | 抽選・お知らせ内容名                          |
| frequency   | string    | 繰り返し単位: "yearly" / "monthly" / "weekly" |
| start_month | int       | yearly の開始月（1〜12）                      |
| start_day   | int       | yearly・monthly の開始日（1〜31）             |
| end_month   | int       | yearly の終了月（1〜12）                      |
| end_day     | int       | yearly・monthly の終了日（1〜31）             |
| weekdays    | text/list | weekly の曜日 (例: ["Mon","Thu"])             |
| messages    | JSON/text | 表示メッセージ（複数可、固定文言）            |

### ■ 表示ルール

* 条件に該当する期間・曜日で **常時表示**
* メッセージは `messages` に複数設定可能

### ■ サンプル

**毎月1〜5日**

* frequency: "monthly"
* start_day: 1
* end_day: 5
* messages: ["抽選開始のお知らせ", "締切に注意してください"]

**毎週月・木**

* frequency: "weekly"
* weekdays: ["Mon", "Thu"]

---

# ■ 今後の拡張予定

* スプレッドシートのバージョン管理強化
* Google Calendar API との連携オプション
* 過去予約の自動アーカイブ

---

必要に応じて、**DEVELOPER_SETUP.md（開発環境 / API 設定）** も作成可能です。
