import tkinter as tk
from tkinter import messagebox
import csv
import os
from datetime import datetime

DATA_PATH = os.path.join("data", "participations.csv")

class ParticipationWindow:
    def __init__(self, master, reservation_info, username):
        self.master = master
        self.reservation_info = reservation_info
        self.username = username

        self.master.title("参加表明")
        self.master.geometry("360x420")

        # --- タイトル表示 ---
        tk.Label(master, text="参加表明画面", font=("Arial", 14, "bold")).pack(pady=5)
        tk.Label(master, text=f"{reservation_info['date']}  {reservation_info['title']}", font=("Arial", 12)).pack(pady=2)

        # --- 参加者リスト ---
        tk.Label(master, text="現在の参加状況", font=("Arial", 11, "underline")).pack(pady=4)
        self.listbox = tk.Listbox(master, width=45, height=10)
        self.listbox.pack(pady=3)

        # --- ボタン ---
        frame = tk.Frame(master)
        frame.pack(pady=10)
        tk.Button(frame, text="〇 参加", bg="#b2f2bb", width=10, command=lambda: self.update_status("〇")).grid(row=0, column=0, padx=5)
        tk.Button(frame, text="× 不参加", bg="#ffa8a8", width=10, command=lambda: self.update_status("×")).grid(row=0, column=1, padx=5)

        tk.Button(master, text="閉じる", command=self.master.destroy).pack(pady=10)

        # 初期データ表示
        self.load_participations()

    # CSVから読み込み
    def load_participations(self):
        self.listbox.delete(0, tk.END)
        if not os.path.exists(DATA_PATH):
            return

        with open(DATA_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row["date"] == self.reservation_info["date"]
                        and row["title"] == self.reservation_info["title"]):
                    display = f"{row['username']}：{row['status']}"
                    self.listbox.insert(tk.END, display)

    # 状態更新
    def update_status(self, status):
        confirm = messagebox.askyesno("確認", f"{status} として登録します。よろしいですか？")
        if not confirm:
            return

        rows = []
        found = False

        if os.path.exists(DATA_PATH):
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 同一ユーザー・日付・タイトルの既存行を更新
                    if (row["date"] == self.reservation_info["date"]
                            and row["title"] == self.reservation_info["title"]
                            and row["username"] == self.username):
                        row["status"] = status
                        row["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        found = True
                    rows.append(row)

        # 新規登録
        if not found:
            rows.append({
                "date": self.reservation_info["date"],
                "title": self.reservation_info["title"],
                "username": self.username,
                "status": status,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

        # CSV保存
        with open(DATA_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "title", "username", "status", "updated_at"])
            writer.writeheader()
            writer.writerows(rows)

        messagebox.showinfo("完了", "参加状況を更新しました。")
        self.load_participations()


# --- 動作テスト用 ---
if __name__ == "__main__":
    root = tk.Tk()
    reservation_info = {"date": "2025-11-20", "title": "朝練"}
    ParticipationWindow(root, reservation_info, username="yossy")
    root.mainloop()
