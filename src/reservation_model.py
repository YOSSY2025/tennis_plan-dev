import tkinter as tk
from tkinter import messagebox
import csv
from datetime import datetime

CSV_FILE = "data/reservations.csv"

class ReservationModal(tk.Toplevel):
    def __init__(self, master, selected_date, refresh_callback):
        super().__init__(master)
        self.title(f"予約詳細 ({selected_date})")
        self.geometry("420x380")
        self.selected_date = selected_date
        self.refresh_callback = refresh_callback
        self.reservations = self.load_reservations()
        self.create_widgets()
        self.grab_set()  # モーダル動作

    def load_reservations(self):
        """CSVから該当日の予約を読み込む"""
        reservations = []
        try:
            with open(CSV_FILE, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["date"] == self.selected_date:
                        reservations.append(row)
        except FileNotFoundError:
            pass
        return reservations

    def create_widgets(self):
        tk.Label(self, text=f"{self.selected_date} の予約一覧", font=("Arial", 12, "bold")).pack(pady=5)

        # 予約リスト表示
        self.listbox = tk.Listbox(self, width=50, height=8)
        for r in self.reservations:
            self.listbox.insert(tk.END, f"{r['time']} - {r['end_time']} {r['title']}")
        self.listbox.pack(pady=5)

        # 入力欄
        tk.Label(self, text="タイトル:").pack()
        self.title_entry = tk.Entry(self, width=40)
        self.title_entry.pack(pady=2)

        tk.Label(self, text="開始時間:").pack()
        self.time_var = tk.StringVar(value="09:00")
        self.time_menu = tk.OptionMenu(self, self.time_var, *[f"{h:02}:00" for h in range(7, 22)])
        self.time_menu.pack()

        tk.Label(self, text="終了時間:").pack()
        self.end_time_var = tk.StringVar(value="10:00")
        self.end_time_menu = tk.OptionMenu(self, self.end_time_var, *[f"{h:02}:00" for h in range(8, 23)])
        self.end_time_menu.pack()

        tk.Label(self, text="メモ:").pack()
        self.desc_text = tk.Text(self, width=40, height=3)
        self.desc_text.pack(pady=3)

        # ボタン群
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="登録", command=self.add_reservation, width=10).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="削除", command=self.delete_reservation, width=10).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text="閉じる", command=self.destroy, width=10).grid(row=0, column=2, padx=5)

    def add_reservation(self):
        title = self.title_entry.get().strip()
        start = self.time_var.get()
        end = self.end_time_var.get()
        desc = self.desc_text.get("1.0", tk.END).strip()

        if not title:
            messagebox.showwarning("入力不足", "タイトルを入力してください。")
            return

        if messagebox.askyesno("確認", f"{self.selected_date} {start}-{end}\n『{title}』を登録しますか？"):
            new_row = {
                "date": self.selected_date,
                "time": start,
                "end_time": end,
                "title": title,
                "description": desc,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            # CSVへ追記
            file_exists = False
            try:
                with open(CSV_FILE, "r", encoding="utf-8") as f:
                    file_exists = True
            except FileNotFoundError:
                pass

            with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=new_row.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(new_row)

            messagebox.showinfo("完了", "予約を登録しました。")
            self.refresh_callback()
            self.destroy()

    def delete_reservation(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("選択なし", "削除する予約を選択してください。")
            return

        index = sel[0]
        target = self.reservations[index]

        if messagebox.askyesno("確認", f"{target['title']} を削除しますか？"):
            updated = []
            with open(CSV_FILE, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not (row["date"] == target["date"] and row["time"] == target["time"] and row["title"] == target["title"]):
                        updated.append(row)

            with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=updated[0].keys())
                writer.writeheader()
                writer.writerows(updated)

            messagebox.showinfo("削除完了", "予約を削除しました。")
            self.refresh_callback()
            self.destroy()
