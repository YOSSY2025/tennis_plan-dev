
# **DEVELOPMENT.md（更新案）**

## 開発手順書

**最終更新日：2025-11-17**

**対象環境：Windows 11 / Python 3.12.4 / Streamlit Community Cloud**

---

## 1. 開発環境

### 1-1. OS

* **Windows 11**

### 1-2. Python

* **Python 3.12.4**
* 推奨パッケージ管理：`venv`（標準）

  ※必須ではないが、仮想環境利用を推奨

### 1-3. 推奨エディタ

* Visual Studio Code
  * 拡張機能：Python、Pylance、GitHub Copilot（任意）

---

## 2. 主要ライブラリ

| ライブラリ名              | 用途                       |
| ------------------------- | -------------------------- |
| **streamlit**       | UI・画面構築               |
| **pandas**          | 予約データの読み込み・加工 |
| **gspread**         | Google Sheets 読み書き     |
| **oauth2client**    | Google API 認証            |
| **python-dotenv**   | API鍵の環境変数管理        |
| **plotly** （任意） | 統計グラフ表示（将来機能） |

### インストール例

<pre class="overflow-visible!" data-start="743" data-end="818"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>pip install streamlit pandas gspread oauth2client python-dotenv
</span></span></code></div></div></pre>

---

## 3. Google Drive / Google Sheets 連携設定


### 3-1. Google Cloud Console の準備

1. [https://console.cloud.google.com](https://console.cloud.google.com) にアクセス
2. 新規プロジェクトを作成
3. 「APIとサービス」→「APIとサービスの有効化」

   * **Google Drive API**
   * **Google Sheets API**

     を有効化する
4. 「認証情報」→「サービスアカウント」を作成
5. 「鍵を追加」→JSON形式でダウンロード

   → `service_account.json` を `project_root/.credentials/` に保存

---

### 3-2. Sheets の共有設定

予約データを保存している Google Sheets を開き、

**サービスアカウントのメールアドレス** を *閲覧者 or 編集者* として追加。

---

### 3-3. Python 側での読み込み例

<pre class="overflow-visible!" data-start="1344" data-end="1820"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-python"><span><span>import</span><span> gspread
</span><span>from</span><span> oauth2client.service_account </span><span>import</span><span> ServiceAccountCredentials
</span><span>import</span><span> pandas </span><span>as</span><span> pd

scope = [</span><span>"https://www.googleapis.com/auth/spreadsheets"</span><span>,
         </span><span>"https://www.googleapis.com/auth/drive"</span><span>]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    </span><span>".credentials/service_account.json"</span><span>,
    scope
)
client = gspread.authorize(creds)

sheet = client.</span><span>open</span><span>(</span><span>"tennis_reservations"</span><span>).sheet1

data = sheet.get_all_records()
df = pd.DataFrame(data)
</span></span></code></div></div></pre>

---

## 4. アプリの実行

### 4-1. ローカル実行方法

<pre class="overflow-visible!" data-start="1860" data-end="1903"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>streamlit run src/tennis_app.py
</span></span></code></div></div></pre>

### 4-2. ローカル実行時の構成

<pre class="overflow-visible!" data-start="1926" data-end="2073"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>project_root/
├─ src/
│   └─ tennis_app.py
├─ docs/
│   └─ …
├─ .credentials/
│   └─ service_account.json
└─ .</span><span>env</span><span> （Google Sheets のシート名等を管理）
</span></span></code></div></div></pre>

---

## 5. デプロイ（Streamlit Community Cloud）

### 5-1. 前提

* ソースを GitHub リポジトリに push 済みであること

### 5-2. 手順

1. [https://streamlit.io/cloud](https://streamlit.io/cloud) にアクセス
2. 「New app」→ GitHub リポジトリを選択
3. Main ブランチ / `src/tennis_app.py` を指定
4. Secrets に Google API 情報を登録
   * `GOOGLE_SERVICE_ACCOUNT_JSON`（サービスアカウントJSON丸ごと）
   * `SHEET_NAME`
5. デプロイ開始 → 数十秒で公開される

---

## 6. バージョン管理（Git）

### 6-1. ブランチ構成

| ブランチ名  | 用途                 |
| ----------- | -------------------- |
| `main`    | 本番デプロイブランチ |
| `dev`     | 日々の開発用         |
| feature/xxx | 個別の機能開発       |

---

## 7. 今後の追加予定（メモ）

* Docker 化（必要になった時点で）
* デプロイ自動化（GitHub Actions）
