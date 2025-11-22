# 📘 **UI_FLOW.md — テニス予約管理アプリ UIフロー図**

---

## 1. 画面一覧

| 画面名       | ファイル内名称              | 主な機能                                   |
| ------------ | --------------------------- | ------------------------------------------ |
| トップ画面   | `TopView`                 | カレンダー表示、予約一覧、抽選リマインダー |
| 予約登録画面 | `RegisterReservationView` | 日付・時間・施設・ステータスの登録         |
| 参加表明画面 | `EntryView`               | 参加/不参加登録、コメント入力、履歴表示    |
| 履歴画面     | `HistoryView`             | 参加・不参加の履歴一覧                     |
| 施設登録画面 | `FacilityView`            | 登録済み施設の追加・編集                   |

---

## 2. 画面遷移図（簡易）

<pre class="overflow-visible!" data-start="466" data-end="934"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>┌────────────────────────┐
│         TopView（トップ）        │
│  ・カレンダー（月表示）          │
│  ・当月予約一覧                  │
│  ・抽選期間リマインダー          │
└───────┬───────────────┘
            │（日付 or イベント選択）
            ▼
┌────────────────────────┐
│ RegisterReservationView（予約登録）│
└───────┬───────────────┘
            │（登録完了）
            ▼
   ○ TopView に戻る


</span><span>From</span><span> TopViewのボタン操作
---------------------------------
</span><span>[参加表明]</span><span> → EntryView
</span><span>[施設登録]</span><span> → FacilityView
</span><span>[履歴]</span><span> → HistoryView
</span></span></code></div></div></pre>

---

## 3. TopView（トップ画面）

### ● UI構成

* カレンダー（月次）
  * PC：左右ボタンで月移動
  * スマホ：**左右スワイプで月移動（新規追加）**
* 抽選期間リマインダー（固定文言／複数表示可）
* 当月の予約一覧（カード形式）
* 予約一覧のイベントタップ → 自動で **参加表明画面**へ遷移（新規仕様）
* 日付をタップ → **予約登録画面**へ遷移（新規仕様）

---

## 4. RegisterReservationView（予約登録画面）

### ● 入力項目

* 日付（タップ元より自動入力）
* 開始時刻
* 終了時刻
* 施設名（プルダウン）
* ステータス（抽選中／確保／中止）

### ● 操作

* 登録ボタン → 登録後 TopView へ戻る。

---

## 5. EntryView（参加表明画面）

### ● 表示項目

* 開催日
* 施設名
* 参加区分（参加 / 不参加 / 検討中）
* ニックネーム（プルダウン）
* コメント欄（1つ、改行OK）

### ● 表示機能（新仕様反映済）

* 参加済み一覧（ **削除不可・最新順** ）

### ● 操作

* 登録ボタン → 追加 → 画面更新

---

## 6. HistoryView（履歴画面）

### ● 内容

* 過去の参加表明履歴（最新順）
* フィルタ（参加／不参加／検討中）

---

## 7. FacilityView（施設登録画面）

### ● 内容

* 登録済み施設一覧
* 新規追加
* 編集

---

## 8. 備考（スマホ UI 仕様）

| 項目           | 内容                             |
| -------------- | -------------------------------- |
| 月移動         | **左右スワイプ対応（新）** |
| 日付タップ     | 自動で予約登録画面へ             |
| イベントタップ | 自動で参加表明画面へ             |
