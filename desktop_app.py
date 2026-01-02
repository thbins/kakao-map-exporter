import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pandas as pd
from kakao_api import geocode_location, bbox_from_center_radius, fetch_places_tiled


# 프랜차이즈 키워드(고정)
FRANCHISE_KEYWORDS = [
    "MGC", "메가커피", "메가", "MEGA",
    "컴포즈", "컴포즈커피", "COMPOSE",
    "스타벅스", "STARBUCKS",
    "빽다방", "PAIK", "이디야", "투썸", "매머드",
]


def is_franchise(name: str) -> bool:
    n = (name or "").strip().lower()
    return any(k.lower() in n for k in FRANCHISE_KEYWORDS)


# 내부 고정 파라미터(사용자 입력 X)
DEFAULT_RADIUS_M = 3000     # 지역 중심 반경 3km 범위 수집
DEFAULT_TILE_DEG = 0.01     # 타일 크기
DEFAULT_SLEEP_SEC = 0.25    # 호출 간 sleep


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("카카오맵 카페 검색기")
        self.geometry("1040x720")

        # 수집 중지용
        self.stop_event = threading.Event()
        self.worker_thread = None

        # UI 페이징 상태
        self.df = pd.DataFrame(columns=["이름", "주소", "전화번호"])
        self.page_size = 50
        self.current_page = 1
        self.total_pages = 1

        # ===== Top =====
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="검색어").grid(row=0, column=0, sticky="w")
        self.query_var = tk.StringVar(value="카페")
        self.query_entry = ttk.Entry(top, textvariable=self.query_var)
        self.query_entry.grid(row=0, column=1, sticky="we", padx=(8, 12))

        ttk.Label(top, text="지역명").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.loc_var = tk.StringVar(value="서울시청")
        self.loc_entry = ttk.Entry(top, textvariable=self.loc_var)
        self.loc_entry.grid(row=1, column=1, sticky="we", padx=(8, 12), pady=(10, 0))

        self.franchise_exclude_var = tk.BooleanVar(value=True)
        self.franchise_chk = ttk.Checkbutton(top, text="프랜차이즈 제외", variable=self.franchise_exclude_var)
        self.franchise_chk.grid(row=0, column=2, sticky="w")

        self.search_btn = ttk.Button(top, text="검색", command=self.on_search)
        self.search_btn.grid(row=1, column=2, sticky="we", pady=(10, 0))

        # Stop 버튼
        self.stop_btn = ttk.Button(top, text="Stop", command=self.on_stop, state="disabled")
        self.stop_btn.grid(row=1, column=3, sticky="we", padx=(8, 0), pady=(10, 0))

        self.query_entry.bind("<Return>", self.on_search_enter)
        self.loc_entry.bind("<Return>", self.on_search_enter)

        # ===== Progress UI =====
        prog = ttk.Frame(self, padding=(12, 0))
        prog.pack(fill="x")

        self.tile_var = tk.StringVar(value="타일 0/0")
        self.collected_var = tk.StringVar(value="누적 0건")
        ttk.Label(prog, textvariable=self.tile_var).pack(side="left")
        ttk.Label(prog, textvariable=self.collected_var).pack(side="left", padx=(12, 0))

        self.pbar = ttk.Progressbar(prog, orient="horizontal", mode="determinate", maximum=100)
        self.pbar.pack(side="right", fill="x", expand=True)

        # ===== Info =====
        info = ttk.Frame(self, padding=(12, 0))
        info.pack(fill="x")

        self.count_var = tk.StringVar(value="총 0건")
        ttk.Label(info, textvariable=self.count_var).pack(side="left")

        self.page_var = tk.StringVar(value="1 / 1")
        ttk.Label(info, textvariable=self.page_var).pack(side="right")

        # ===== Table =====
        table_frame = ttk.Frame(self, padding=(12, 8))
        table_frame.pack(fill="both", expand=True)

        # ✅ No 컬럼 추가
        cols = ("no", "name", "addr", "phone")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=20)

        self.tree.heading("no", text="No")
        self.tree.heading("name", text="이름")
        self.tree.heading("addr", text="주소")
        self.tree.heading("phone", text="전화번호")

        self.tree.column("no", width=60, anchor="e")
        self.tree.column("name", width=250, anchor="w")
        self.tree.column("addr", width=450, anchor="w")
        self.tree.column("phone", width=140, anchor="w")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # ===== Bottom =====
        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.pack(fill="x")

        self.status_var = tk.StringVar(
            value=f"지역명→좌표 자동 변환 후 반경 {DEFAULT_RADIUS_M//1000}km로 45개 이상 수집(타일링)."
        )
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left", fill="x", expand=True)

        # ✅ 오른쪽 버튼 영역(2줄 + 텍스트 변경)
        btn_area = ttk.Frame(bottom)
        btn_area.pack(side="right")

        nav_row = ttk.Frame(btn_area)
        nav_row.pack(fill="x")

        self.prev_btn = ttk.Button(nav_row, text="이전 페이지", command=self.on_prev, state="disabled")
        self.prev_btn.pack(side="left", padx=(0, 8))

        self.next_btn = ttk.Button(nav_row, text="다음 페이지", command=self.on_next, state="disabled")
        self.next_btn.pack(side="left")

        save_row = ttk.Frame(btn_area)
        save_row.pack(fill="x", pady=(6, 0))

        self.save_btn = ttk.Button(save_row, text="엑셀로 저장...", command=self.on_save, state="disabled")
        self.save_btn.pack(side="left", fill="x", expand=True)

        # 실행 시 포커스 안정화
        self.bind("<Map>", self._focus_query_once)

    def _focus_query_once(self, event=None):
        if getattr(self, "_focused_once", False):
            return
        self._focused_once = True

        def do_focus():
            try:
                self.deiconify()
                self.lift()
                self.attributes("-topmost", True)
                self.attributes("-topmost", False)
            except Exception:
                pass
            try:
                self.query_entry.focus_force()
                self.query_entry.icursor("end")
            except Exception:
                pass

        self.after(150, do_focus)

    # ---------- helpers ----------
    def clear_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def refresh_pagination_buttons(self):
        self.prev_btn.config(state="normal" if self.current_page > 1 else "disabled")
        self.next_btn.config(state="normal" if self.current_page < self.total_pages else "disabled")

    def compute_total_pages(self):
        n = len(self.df)
        self.total_pages = max(1, (n + self.page_size - 1) // self.page_size)

    def render_current_page(self):
        self.clear_table()
        if self.df.empty:
            self.page_var.set("1 / 1")
            self.refresh_pagination_buttons()
            return

        start = (self.current_page - 1) * self.page_size
        end = start + self.page_size
        page_df = self.df.iloc[start:end]

        # ✅ 전체 데이터 기준 1부터 No 부여
        for i, (_, row) in enumerate(page_df.iterrows(), start=start + 1):
            self.tree.insert("", "end", values=(i, row["이름"], row["주소"], row["전화번호"]))

        self.page_var.set(f"{self.current_page} / {self.total_pages}")
        self.refresh_pagination_buttons()

    def set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.search_btn.config(state=state)
        self.query_entry.config(state=state)
        self.loc_entry.config(state=state)
        self.franchise_chk.config(state=state)
        self.stop_btn.config(state="normal" if busy else "disabled")

    def reset_progress(self):
        self.tile_var.set("타일 0/0")
        self.collected_var.set("누적 0건")
        self.pbar["value"] = 0
        self.pbar["maximum"] = 100

    # ---------- events ----------
    def on_search_enter(self, event=None):
        if str(self.search_btn["state"]) == "disabled":
            return
        self.on_search()

    def on_stop(self):
        self.stop_event.set()
        self.status_var.set("중지 요청됨... 현재 작업을 정리하는 중")

    def on_search(self):
        query = self.query_var.get().strip()
        loc = self.loc_var.get().strip()

        if not query:
            messagebox.showerror("오류", "검색어를 입력하세요.")
            return
        if not loc:
            messagebox.showerror("오류", "지역명을 입력하세요.")
            return

        self.stop_event.clear()
        self.reset_progress()

        self.status_var.set("좌표 변환/수집 중...")
        self.count_var.set("총 0건")
        self.save_btn.config(state="disabled")
        self.prev_btn.config(state="disabled")
        self.next_btn.config(state="disabled")
        self.clear_table()
        self.set_busy(True)

        self.worker_thread = threading.Thread(target=self._run_search, args=(query, loc), daemon=True)
        self.worker_thread.start()

    def _run_search(self, query: str, loc: str):
        try:
            x, y = geocode_location(loc)
            bbox = bbox_from_center_radius(x, y, DEFAULT_RADIUS_M)

            def progress_cb(tile_idx: int, total_tiles: int, total_collected: int):
                def _ui():
                    self.tile_var.set(f"타일 {tile_idx}/{total_tiles}")
                    self.collected_var.set(f"누적 {total_collected}건")
                    self.pbar["maximum"] = max(1, total_tiles)
                    self.pbar["value"] = tile_idx
                self.after(0, _ui)

            rows = fetch_places_tiled(
                query=query,
                bbox=bbox,
                tile_deg=DEFAULT_TILE_DEG,
                sleep_sec=DEFAULT_SLEEP_SEC,
                stop_event=self.stop_event,
                on_progress=progress_cb,
            )

            exclude_franchise = self.franchise_exclude_var.get()
            excluded_count = 0

            normalized = []
            for r in rows:
                name = (r.get("이름") or "").strip()
                if exclude_franchise and is_franchise(name):
                    excluded_count += 1
                    continue

                road = (r.get("도로명주소") or "").strip()
                jibun = (r.get("지번주소") or "").strip()
                addr = road if road else jibun

                normalized.append({
                    "이름": name,
                    "주소": addr,
                    "전화번호": (r.get("전화번호") or "").strip(),
                })

            df = pd.DataFrame(normalized)
            if not df.empty:
                df = df.drop_duplicates(subset=["이름", "주소", "전화번호"])

            was_stopped = self.stop_event.is_set()
            self.after(0, lambda: self._apply_results(df, x, y, excluded_count, exclude_franchise, was_stopped))

        except Exception as e:
            self.after(0, lambda: self._show_error(e))
        finally:
            self.after(0, lambda: self.set_busy(False))

    def _apply_results(self, df: pd.DataFrame, x: float, y: float, excluded: int, excluded_on: bool, was_stopped: bool):
        self.df = df
        n = len(df)

        if excluded_on:
            self.count_var.set(f"총 {n}건 (프랜차이즈 제외 {excluded}건)")
        else:
            self.count_var.set(f"총 {n}건")

        if n == 0:
            self.status_var.set("검색 결과가 없습니다." if not was_stopped else "중지됨. (부분 결과 없음)")
            self.save_btn.config(state="disabled")
            return

        self.compute_total_pages()
        self.current_page = 1
        self.render_current_page()
        self.save_btn.config(state="normal")

        if was_stopped:
            self.status_var.set(f"중지됨. 부분 결과 {n}건 표시 중. 좌표=({x:.6f}, {y:.6f})")
        else:
            self.status_var.set(f"완료. 좌표=({x:.6f}, {y:.6f}) / 이전/다음 페이지 / 엑셀 저장 가능.")

    def _show_error(self, e: Exception):
        self.status_var.set("오류가 발생했습니다.")
        messagebox.showerror("오류", str(e))
        self.save_btn.config(state="disabled")
        self.prev_btn.config(state="disabled")
        self.next_btn.config(state="disabled")

    def on_prev(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.render_current_page()

    def on_next(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.render_current_page()

    def on_save(self):
        if self.df.empty:
            messagebox.showinfo("안내", "저장할 데이터가 없습니다. 먼저 검색하세요.")
            return

        query = self.query_var.get().strip() or "results"
        loc = self.loc_var.get().strip() or "location"
        initial = f"{loc}_{query}_results.xlsx"

        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=initial,
        )
        if not path:
            return

        try:
            # ✅ 저장할 때도 No 컬럼 추가
            df_out = self.df.copy()
            df_out.insert(0, "No", range(1, len(df_out) + 1))

            df_out.to_excel(path, index=False)
            messagebox.showinfo("완료", f"저장 완료!\n{path}")
        except Exception as e:
            messagebox.showerror("오류", str(e))


if __name__ == "__main__":
    App().mainloop()