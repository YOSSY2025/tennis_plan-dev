import tkinter as tk
from tkinter import ttk
import csv
import os
from datetime import datetime, date

DATA_PATH = os.path.join("data", "lottery_periods.csv")

class LotteryPeriodWindow:
    def __init__(self, master):
        self.master = master
        self.master.title("抽選期間確認")
        self.master.geometry("520x360")

        tk.Label(master, text="抽選期間一覧", font=("Arial", 14, "bold")).pack(pady=8)

        # Treeviewテーブル
        columns = ("name", "period", "target")
        self.tree = ttk.Treeview(master, columns=columns, show="headings", height=10)
        self.tree.heading("name", text="抽選名")
        self.tree.heading("period", text="応募期間")
        self.tree.heading("target", text="対象期間")
        self.tree.pack(pady=5, fill=tk.BOTH, expand=True)

        ttk.Button(master, text="閉じる", command=self.master.destroy).pack(pady=8)

        self.load_data()

    def load_data(self):
        if not os.path.exists(DATA_PATH):
            return

        today = date.today()
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                start = datetime.strptime(row["start_date"], "%Y-%m-%d").date()
                end = datetime.strptime(row["end_date"], "%Y-%m-%d").date()
                period_str = f"{start.strftime('%m/%d')}～{end.strftime('%m/%d')}"
                target_str = row["target_period"]

                item = self.tree.insert("", "end", values=(row["lottery_name"], period_str, target_str))

                # 応募期間中は緑色で強調
                if start <= today <= end:
                    self.tree.item(item, tags=("active",))

        self.tree.tag_configure("active", background="#b2f2bb")  # 緑色背景

# --- 動作テスト用 ---
if __name__ == "__main__":
    root = tk.Tk()
    LotteryPeriodWindow(root)
    root.mainloop()
