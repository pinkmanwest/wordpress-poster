import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog, filedialog
import threading
import queue
import os
import requests
from datetime import datetime

from config import FALLBACK_MODELS, HAS_MARKDOWN, load_config, save_config, parse_lines, parse_sites, extract_variables, extract_domains
from openrouter import OpenRouterClient
from wordpress import WordPressClient
from worker import PostWorker



class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WordPress AI Poster")
        self.geometry("950x740")
        self.minsize(820, 620)

        self._cfg = load_config()
        self._workers: list[PostWorker] = []
        self._task_queue: queue.Queue = queue.Queue()
        self._active_workers = 0
        self._tasks_done = 0
        self._lock = threading.Lock()
        self._favorites: list[str] = []
        self._saved_prompts: list[dict] = []
        self._csv_lock = threading.Lock()

        self._build_ui()
        self._apply_config()
        self._autoload_models()

    # ── UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TLabelframe.Label", font=("Segoe UI", 9, "bold"))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self._nb = nb

        f1 = ttk.Frame(nb)
        nb.add(f1, text="  ⚙  Настройки  ")
        self._build_settings(f1)

        f2 = ttk.Frame(nb)
        nb.add(f2, text="  🏷  Категории и теги  ")
        self._build_metadata(f2)

        f3 = ttk.Frame(nb)
        nb.add(f3, text="  🚀  Генерация и публикация  ")
        self._build_generate(f3)

        f4 = ttk.Frame(nb)
        nb.add(f4, text="  🔍  Проверка XML-RPC  ")
        self._build_checker(f4)

    # ── Tab 1: Settings ──────────────────────────────────────────

    def _build_settings(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        # WordPress sites
        wp = ttk.LabelFrame(parent, text="WordPress сайты", padding=10)
        wp.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        wp.rowconfigure(1, weight=1)
        wp.columnconfigure(0, weight=1)

        ttk.Label(
            wp,
            text="Формат: https://example.invalid:логин:пароль  (по одному на строку, # — комментарий)",
            foreground="gray",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.sites_text = scrolledtext.ScrolledText(wp, height=6, font=("Consolas", 9))
        self.sites_text.grid(row=1, column=0, sticky="nsew")
        self.sites_text.insert("1.0", "# https://example.invalid:YOUR_USERNAME:YOUR_WORDPRESS_PASSWORD\n")

        ttk.Button(wp, text="Проверить все подключения", command=self._test_wp).grid(
            row=2, column=0, sticky="w", pady=(6, 0))

        # OpenRouter
        or_ = ttk.LabelFrame(parent, text="OpenRouter AI", padding=10)
        or_.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        or_.columnconfigure(1, weight=1)

        # API Key
        ttk.Label(or_, text="API Key:").grid(row=0, column=0, sticky="w", pady=4)
        self.or_key = ttk.Entry(or_, width=50, show="*")
        self.or_key.grid(row=0, column=1, columnspan=2, sticky="ew", padx=6, pady=4)
        self.or_key.bind("<FocusOut>", lambda _: self._autoload_models())

        # Model row
        ttk.Label(or_, text="Модель:").grid(row=1, column=0, sticky="w", pady=4)
        self.or_model = ttk.Combobox(or_, width=46, values=FALLBACK_MODELS)
        self.or_model.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        self.or_model.set(FALLBACK_MODELS[0])

        model_btns = ttk.Frame(or_)
        model_btns.grid(row=1, column=2, sticky="w", padx=(0, 4), pady=4)
        ttk.Button(model_btns, text="☆", width=3, command=self._add_favorite).pack(side="left", padx=1)
        ttk.Button(model_btns, text="↺", width=3, command=self._load_models).pack(side="left", padx=1)

        self.models_status = ttk.Label(or_, text="", foreground="gray")
        self.models_status.grid(row=2, column=1, columnspan=2, sticky="w", padx=6)

        # Favorites
        ttk.Label(or_, text="Избранные:").grid(row=3, column=0, sticky="nw", pady=(8, 4))

        fav_wrap = ttk.Frame(or_)
        fav_wrap.grid(row=3, column=1, sticky="ew", padx=6, pady=(8, 4))
        fav_wrap.columnconfigure(0, weight=1)

        self.fav_list = tk.Listbox(fav_wrap, height=4, selectmode="single",
                                   exportselection=False, font=("Consolas", 9))
        self.fav_list.grid(row=0, column=0, sticky="ew")
        self.fav_list.bind("<Double-1>", self._select_favorite)

        sb = ttk.Scrollbar(fav_wrap, orient="vertical", command=self.fav_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.fav_list.config(yscrollcommand=sb.set)

        ttk.Label(fav_wrap, text="Двойной клик — выбрать", foreground="gray").grid(
            row=1, column=0, sticky="w")

        ttk.Button(or_, text="✕ Убрать", command=self._remove_favorite).grid(
            row=3, column=2, sticky="nw", padx=(0, 4), pady=(8, 4))

        ttk.Button(parent, text="💾  Сохранить настройки", command=self._save_settings).grid(
            row=2, column=0, pady=10)

    # ── Tab 2: Metadata ──────────────────────────────────────────

    def _build_metadata(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        cf = ttk.LabelFrame(parent, text="Категории", padding=10)
        cf.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        cf.rowconfigure(1, weight=1)
        cf.columnconfigure(0, weight=1)

        ttk.Label(cf, text="Введите категории (по одной на строку):").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.cat_text = scrolledtext.ScrolledText(cf, height=12, width=28)
        self.cat_text.grid(row=1, column=0, sticky="nsew")

        pf = ttk.Frame(cf)
        pf.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(pf, text="Выбирать случайно:").pack(side="left")
        self.cat_pick = ttk.Spinbox(pf, from_=0, to=50, width=5)
        self.cat_pick.set("2")
        self.cat_pick.pack(side="left", padx=5)
        ttk.Label(pf, text="кат. на пост").pack(side="left")

        tf = ttk.LabelFrame(parent, text="Метки (теги)", padding=10)
        tf.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        tf.rowconfigure(1, weight=1)
        tf.columnconfigure(0, weight=1)

        ttk.Label(tf, text="Введите теги (по одной на строку):").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.tag_text = scrolledtext.ScrolledText(tf, height=12, width=28)
        self.tag_text.grid(row=1, column=0, sticky="nsew")

        pf2 = ttk.Frame(tf)
        pf2.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(pf2, text="Выбирать случайно:").pack(side="left")
        self.tag_pick = ttk.Spinbox(pf2, from_=0, to=100, width=5)
        self.tag_pick.set("3")
        self.tag_pick.pack(side="left", padx=5)
        ttk.Label(pf2, text="тегов на пост").pack(side="left")

        opt = ttk.LabelFrame(parent, text="Параметры поста", padding=10)
        opt.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))

        ttk.Label(opt, text="Комментарии (выберите варианты — один выбирается случайно):").pack(anchor="w")
        chk = ttk.Frame(opt)
        chk.pack(fill="x", pady=3)
        self.comment_open = tk.BooleanVar(value=True)
        self.comment_closed = tk.BooleanVar(value=False)
        ttk.Checkbutton(chk, text="Открыты (open)", variable=self.comment_open).pack(side="left", padx=10)
        ttk.Checkbutton(chk, text="Закрыты (closed)", variable=self.comment_closed).pack(side="left", padx=10)

        row2 = ttk.Frame(opt)
        row2.pack(fill="x", pady=6)
        ttk.Label(row2, text="Статус публикации:").pack(side="left")
        self.post_status = ttk.Combobox(row2, values=["publish", "draft", "private", "pending"], width=12)
        self.post_status.set("publish")
        self.post_status.pack(side="left", padx=8)

        row3 = ttk.Frame(opt)
        row3.pack(fill="x", pady=3)
        self.md_to_html = tk.BooleanVar(value=True)
        md_cb = ttk.Checkbutton(row3, text="Конвертировать Markdown → HTML", variable=self.md_to_html)
        md_cb.pack(side="left", padx=10)
        if not HAS_MARKDOWN:
            md_cb.config(state="disabled")
            ttk.Label(row3, text="(pip install markdown)", foreground="gray").pack(side="left")

        row4 = ttk.Frame(opt)
        row4.pack(fill="x", pady=3)
        self.toc_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(row4, text="Генерировать содержание (TOC)", variable=self.toc_enabled).pack(side="left", padx=10)
        ttk.Label(row4, text="Заголовок:").pack(side="left", padx=(10, 4))
        self.toc_title = ttk.Entry(row4, width=20)
        self.toc_title.insert(0, "Contents")
        self.toc_title.pack(side="left")

    # ── Tab 3: Generate & Post ───────────────────────────────────

    def _build_generate(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(5, weight=1)
        parent.columnconfigure(0, weight=1)

        # Prompts frame
        pf = ttk.LabelFrame(parent, text="Промты", padding=10)
        pf.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        pf.rowconfigure(2, weight=2)
        pf.rowconfigure(4, weight=1)
        pf.columnconfigure(0, weight=1)

        # Saved prompts bar
        pm = ttk.Frame(pf)
        pm.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(pm, text="Сохранённые:").pack(side="left")
        self.saved_prompt_cb = ttk.Combobox(pm, width=22, state="readonly")
        self.saved_prompt_cb.pack(side="left", padx=(4, 6))
        ttk.Button(pm, text="Загрузить", command=self._load_prompt).pack(side="left", padx=2)
        ttk.Button(pm, text="Сохранить", command=self._save_prompt).pack(side="left", padx=2)
        ttk.Button(pm, text="Удалить",   command=self._delete_prompt).pack(side="left", padx=2)

        ttk.Separator(pf, orient="horizontal").grid(row=1, column=0, sticky="ew", pady=(0, 6))

        # Content prompt
        hint = ttk.Frame(pf)
        hint.grid(row=2, column=0, sticky="ew")
        ttk.Label(hint, text="Промт для контента:").pack(side="left")
        ttk.Label(hint, text="используйте {переменная} для динамических значений",
                  foreground="gray").pack(side="left", padx=8)
        self.prompt_text = scrolledtext.ScrolledText(pf, height=6)
        self.prompt_text.grid(row=3, column=0, sticky="nsew", pady=(2, 6))

        # Title prompt
        ttk.Label(
            pf,
            text="Промт для заголовка (используйте {content}; оставьте пустым — заголовок из первой строки):",
        ).grid(row=4, column=0, sticky="sw")
        self.title_prompt_text = scrolledtext.ScrolledText(pf, height=3)
        self.title_prompt_text.grid(row=5, column=0, sticky="nsew", pady=(2, 6))

        # Variables section
        var_header = ttk.Frame(pf)
        var_header.grid(row=6, column=0, sticky="ew")
        ttk.Label(var_header, text="Переменные:", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(var_header, text="🔍 Найти в промте", command=self._scan_variables).pack(side="left", padx=8)

        self._vars_outer = ttk.Frame(pf)
        self._vars_outer.grid(row=7, column=0, sticky="ew", pady=(4, 0))
        self._vars_outer.columnconfigure(1, weight=1)
        self._var_entries: dict[str, ttk.Entry] = {}
        self._vars_hint = ttk.Label(self._vars_outer,
                                    text="Нажмите «Найти в промте» или загрузите сохранённый промт",
                                    foreground="gray")
        self._vars_hint.grid(row=0, column=0, columnspan=2, sticky="w")

        # Controls
        ctrl = ttk.Frame(parent)
        ctrl.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        for lbl, attr, lo, hi, default, suffix in [
            ("Потоков:", "thread_count", 1, 20, 2, ""),
            ("Задержка (сек):", "delay_sec", 0, 300, 0, "между постами"),
        ]:
            ttk.Label(ctrl, text=lbl).pack(side="left")
            sb = ttk.Spinbox(ctrl, from_=lo, to=hi, width=5)
            sb.set(str(default))
            sb.pack(side="left", padx=(3, 12))
            if suffix:
                ttk.Label(ctrl, text=suffix, foreground="gray").pack(side="left", padx=(0, 12))
            setattr(self, attr, sb)

        # Buttons
        btns = ttk.Frame(parent)
        btns.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        self.start_btn = ttk.Button(btns, text="▶  Начать публикацию", command=self._start)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(btns, text="■  Остановить", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="🧪 Тест", command=self._test_publish).pack(side="left")
        ttk.Button(btns, text="Очистить лог", command=self._clear_log).pack(side="right")

        self.progress = ttk.Progressbar(parent, mode="determinate")
        self.progress.grid(row=3, column=0, sticky="ew", padx=8, pady=2)
        self.progress_lbl = ttk.Label(parent, text="", foreground="gray")
        self.progress_lbl.grid(row=4, column=0, sticky="w", padx=10)

        # Log
        lf = ttk.LabelFrame(parent, text="Лог", padding=5)
        lf.grid(row=5, column=0, sticky="nsew", padx=8, pady=(4, 8))
        lf.rowconfigure(0, weight=1)
        lf.columnconfigure(0, weight=1)
        self.log_box = scrolledtext.ScrolledText(lf, state="disabled", font=("Consolas", 9), height=8)
        self.log_box.grid(row=0, column=0, sticky="nsew")
        self.log_box.tag_config("ok", foreground="#1a8a1a")
        self.log_box.tag_config("err", foreground="#cc0000")
        self.log_box.tag_config("info", foreground="#0066cc")

    # ── Config ───────────────────────────────────────────────────

    def _apply_config(self):
        c = self._cfg

        if c.get("sites"):
            self.sites_text.delete("1.0", "end")
            self.sites_text.insert("1.0", c["sites"])
        if c.get("or", {}).get("api_key"):
            self.or_key.insert(0, c["or"]["api_key"])
        if c.get("or", {}).get("model"):
            self.or_model.set(c["or"]["model"])
        if c.get("categories"):
            self.cat_text.insert("1.0", c["categories"])
        if c.get("tags"):
            self.tag_text.insert("1.0", c["tags"])

        for attr, key in [("cat_pick", "cat_pick"), ("tag_pick", "tag_pick"),
                           ("thread_count", "thread_count"), ("delay_sec", "delay_sec")]:
            if c.get(key):
                w = getattr(self, attr)
                w.delete(0, "end")
                w.insert(0, str(c[key]))

        if c.get("post_status"):
            self.post_status.set(c["post_status"])
        if "comment_open" in c:
            self.comment_open.set(c["comment_open"])
        if "comment_closed" in c:
            self.comment_closed.set(c["comment_closed"])
        if "md_to_html" in c:
            self.md_to_html.set(c["md_to_html"])
        if c.get("content_prompt"):
            self.prompt_text.insert("1.0", c["content_prompt"])
        if c.get("title_prompt"):
            self.title_prompt_text.insert("1.0", c["title_prompt"])

        # Favorites
        self._favorites = c.get("favorite_models", [])
        self._refresh_favorites()

        # Saved prompts
        self._saved_prompts = c.get("saved_prompts", [])
        self._refresh_saved_prompts()

    def _save_settings(self):
        save_config({
            "sites": self.sites_text.get("1.0", "end").strip(),
            "or": {
                "api_key": self.or_key.get().strip(),
                "model": self.or_model.get().strip(),
            },
            "categories": self.cat_text.get("1.0", "end").strip(),
            "tags": self.tag_text.get("1.0", "end").strip(),
            "cat_pick": self.cat_pick.get(),
            "tag_pick": self.tag_pick.get(),
            "post_status": self.post_status.get(),
            "comment_open": self.comment_open.get(),
            "comment_closed": self.comment_closed.get(),
            "md_to_html": self.md_to_html.get(),
            "thread_count": self.thread_count.get(),
            "delay_sec": self.delay_sec.get(),
            "content_prompt": self.prompt_text.get("1.0", "end").strip(),
            "title_prompt": self.title_prompt_text.get("1.0", "end").strip(),
            "favorite_models": self._favorites,
            "saved_prompts": self._saved_prompts,
        })
        messagebox.showinfo("Сохранено", "Настройки сохранены!")

    def _quick_save(self):
        """Save only favorites and prompts without showing a dialog."""
        c = load_config()
        c["favorite_models"] = self._favorites
        c["saved_prompts"] = self._saved_prompts
        save_config(c)

    # ── Logging ──────────────────────────────────────────────────

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")

        def _append():
            self.log_box.config(state="normal")
            tag = ""
            if "✓" in msg or "Опубликовано" in msg:
                tag = "ok"
            elif "✗" in msg or "Ошибка" in msg:
                tag = "err"
            elif any(k in msg for k in ("Генерирую", "Задержка", "Загружаю", "Проверяю", "Запускаю")):
                tag = "info"
            self.log_box.insert("end", f"[{ts}] {msg}\n", tag)
            self.log_box.see("end")
            self.log_box.config(state="disabled")

        self.after(0, _append)

    def _clear_log(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    # ── Favorites ────────────────────────────────────────────────

    def _refresh_favorites(self):
        self.fav_list.delete(0, "end")
        for m in self._favorites:
            self.fav_list.insert("end", m)

    def _add_favorite(self):
        model = self.or_model.get().strip()
        if not model or model in self._favorites:
            return
        self._favorites.append(model)
        self._refresh_favorites()
        self._quick_save()

    def _remove_favorite(self):
        sel = self.fav_list.curselection()
        if not sel:
            return
        self._favorites.pop(sel[0])
        self._refresh_favorites()
        self._quick_save()

    def _select_favorite(self, _event=None):
        sel = self.fav_list.curselection()
        if not sel:
            return
        self.or_model.set(self._favorites[sel[0]])

    # ── Models ───────────────────────────────────────────────────

    def _autoload_models(self):
        if self.or_key.get().strip():
            self._load_models(silent=True)

    def _load_models(self, silent: bool = False):
        def _run():
            key = self.or_key.get().strip()
            if not key:
                if not silent:
                    self._log("✗ Введите API Key")
                return
            try:
                self.after(0, lambda: self.models_status.config(text="Загружаю модели…"))
                models = OpenRouterClient(key, "").list_models()
                current = self.or_model.get()
                self.after(0, lambda: self.or_model.config(values=models))
                if current not in models and models:
                    self.after(0, lambda: self.or_model.set(models[0]))
                self.after(0, lambda: self.models_status.config(text=f"Загружено {len(models)} моделей"))
                if not silent:
                    self._log(f"✓ Загружено {len(models)} моделей")
            except Exception as e:
                self.after(0, lambda: self.models_status.config(text="Ошибка загрузки"))
                if not silent:
                    self._log(f"✗ Ошибка: {e}")

        threading.Thread(target=_run, daemon=True).start()

    # ── Saved prompts ─────────────────────────────────────────────

    def _refresh_saved_prompts(self):
        names = [p["name"] for p in self._saved_prompts]
        self.saved_prompt_cb.config(values=names)
        if names:
            self.saved_prompt_cb.set(names[0])

    def _scan_variables(self):
        prompt = self.prompt_text.get("1.0", "end")
        title = self.title_prompt_text.get("1.0", "end")
        self._update_var_fields(extract_variables(prompt + "\n" + title))

    def _update_var_fields(self, variables: list[str]):
        for w in self._vars_outer.winfo_children():
            w.destroy()
        self._var_entries.clear()

        if not variables:
            ttk.Label(self._vars_outer, text="Переменных не найдено", foreground="gray").grid(
                row=0, column=0, sticky="w")
            return

        for i, var in enumerate(variables):
            ttk.Label(self._vars_outer, text=f"{{{var}}}:").grid(
                row=i, column=0, sticky="w", padx=(0, 8), pady=2)
            e = ttk.Entry(self._vars_outer, width=42)
            e.grid(row=i, column=1, sticky="ew", pady=2)
            self._var_entries[var] = e

    def _save_prompt(self):
        name = simpledialog.askstring("Сохранить промт", "Название промта:", parent=self)
        if not name:
            return
        entry = {
            "name": name,
            "content": self.prompt_text.get("1.0", "end").strip(),
            "title_prompt": self.title_prompt_text.get("1.0", "end").strip(),
        }
        # Overwrite if same name
        for i, p in enumerate(self._saved_prompts):
            if p["name"] == name:
                self._saved_prompts[i] = entry
                self._refresh_saved_prompts()
                self.saved_prompt_cb.set(name)
                self._quick_save()
                return
        self._saved_prompts.append(entry)
        self._refresh_saved_prompts()
        self.saved_prompt_cb.set(name)
        self._quick_save()

    def _load_prompt(self):
        name = self.saved_prompt_cb.get()
        entry = next((p for p in self._saved_prompts if p["name"] == name), None)
        if not entry:
            return
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", entry["content"])
        self.title_prompt_text.delete("1.0", "end")
        self.title_prompt_text.insert("1.0", entry.get("title_prompt", ""))
        self._scan_variables()

    def _delete_prompt(self):
        name = self.saved_prompt_cb.get()
        self._saved_prompts = [p for p in self._saved_prompts if p["name"] != name]
        self._refresh_saved_prompts()
        self._quick_save()

    # ── WordPress ────────────────────────────────────────────────

    def _test_wp(self):
        sites = parse_sites(self.sites_text.get("1.0", "end"))
        if not sites:
            messagebox.showwarning("Нет сайтов", "Добавьте сайты в формате\nhttps://example.invalid:логин:пароль")
            return

        def _run():
            for cfg in sites:
                try:
                    self._log(f"Проверяю {cfg['url']}...")
                    profile = WordPressClient(**cfg).test()
                    name = profile.get("display_name") or profile.get("user_login") or "?"
                    self._log(f"✓ {cfg['url']} — пользователь: {name}")
                except Exception as e:
                    self._log(f"✗ {cfg['url']} — {e}")

        threading.Thread(target=_run, daemon=True).start()

    # ── Post settings ─────────────────────────────────────────────

    def _build_post_settings(self) -> dict:
        cats = parse_lines(self.cat_text.get("1.0", "end"))
        tags = parse_lines(self.tag_text.get("1.0", "end"))
        comment_opts = []
        if self.comment_open.get():
            comment_opts.append("open")
        if self.comment_closed.get():
            comment_opts.append("closed")
        return {
            "categories": cats,
            "cat_pick": int(self.cat_pick.get()),
            "tags": tags,
            "tag_pick": int(self.tag_pick.get()),
            "comment_options": comment_opts or ["open"],
            "post_status": self.post_status.get(),
            "toc": self.toc_enabled.get(),
            "toc_title": self.toc_title.get().strip() or "Contents",
        }

    # ── Start / Stop ──────────────────────────────────────────────

    def _start(self):
        wp_cfgs = parse_sites(self.sites_text.get("1.0", "end"))
        or_cfg = {
            "api_key": self.or_key.get().strip(),
            "model": self.or_model.get().strip(),
        }
        prompt = self.prompt_text.get("1.0", "end").strip()
        title_prompt = self.title_prompt_text.get("1.0", "end").strip()

        # Substitute variables from inline fields
        for var, entry in self._var_entries.items():
            val = entry.get()
            prompt = prompt.replace(f"{{{var}}}", val)
            title_prompt = title_prompt.replace(f"{{{var}}}", val)

        if not wp_cfgs:
            messagebox.showerror("Ошибка", "Добавьте хотя бы один сайт в настройках")
            return
        if not or_cfg["api_key"] or not or_cfg["model"]:
            messagebox.showerror("Ошибка", "Заполните настройки OpenRouter")
            return
        if not prompt:
            messagebox.showerror("Ошибка", "Введите промт для контента")
            return

        count = len(wp_cfgs)
        threads = min(int(self.thread_count.get()), count)
        delay = float(self.delay_sec.get())
        to_html = self.md_to_html.get() and HAS_MARKDOWN
        self._total_count = count

        self._task_queue = queue.Queue()
        for i in range(count):
            self._task_queue.put({
                "id": i + 1,
                "prompt": prompt,
                "title_prompt": title_prompt,
                "wp_cfg": wp_cfgs[i],
            })

        self._tasks_done = 0
        self._published_count = 0
        self.progress.config(maximum=count, value=0)
        self._update_progress(0, count)
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

        with self._lock:
            self._active_workers = threads

        self._log(f"Запускаю {threads} поток(ов), {count} пост(ов)...")
        self._workers = []
        for _ in range(threads):
            w = PostWorker(
                task_queue=self._task_queue,
                log_fn=self._log,
                on_task_done=self._on_task_done,
                on_worker_done=self._on_worker_done,
                on_published=self._on_published,
                wp_cfgs=wp_cfgs,
                or_cfg=or_cfg,
                post_settings=self._build_post_settings(),
                delay=delay,
                to_html=to_html,
            )
            self._workers.append(w)
            w.start()

    def _on_task_done(self):
        with self._lock:
            self._tasks_done += 1
            done = self._tasks_done
        total = self._total_count
        self.after(0, lambda: (
            self.progress.config(value=done),
            self._update_progress(done, total),
        ))

    def _on_worker_done(self):
        with self._lock:
            self._active_workers -= 1
            last = self._active_workers == 0
        if last:
            self.after(0, self._finish)

    def _finish(self):
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        failed = self._total_count - self._published_count
        msg = f"✓ Всё готово! Опубликовано: {self._published_count}/{self._total_count}"
        if failed:
            msg += f"  ({failed} ошибок)"
        self._log(msg)

    def _stop(self):
        for w in self._workers:
            w.stop()
        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
                self._task_queue.task_done()
            except queue.Empty:
                break
        self._log("Остановлено пользователем")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _on_published(self, site_url: str, post_id: str, title: str, link: str):
        results_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.txt")
        with self._csv_lock:
            self._published_count += 1
            with open(results_file, "a", encoding="utf-8") as f:
                f.write(link + "\n")

    def _test_publish(self):
        wp_cfgs = parse_sites(self.sites_text.get("1.0", "end"))
        if not wp_cfgs:
            messagebox.showerror("Ошибка", "Нет сайтов в настройках")
            return

        def _run():
            for cfg in wp_cfgs:
                try:
                    wp = WordPressClient(**cfg)
                    post_id = wp.new_post(
                        title="Test",
                        content="<p>Test post — can be deleted.</p>",
                        post_status="draft",
                    )
                    self._log(f"✓ {cfg['url']} — тест ОК, черновик ID: {post_id}")
                except Exception as e:
                    self._log(f"✗ {cfg['url']} — {e}")

        threading.Thread(target=_run, daemon=True).start()

    # ── XML-RPC Checker tab ───────────────────────────────────────

    def _build_checker(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(2, weight=2)
        parent.columnconfigure(0, weight=1)

        # Input
        inp = ttk.LabelFrame(parent, text="Домены для проверки", padding=10)
        inp.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        inp.rowconfigure(1, weight=1)
        inp.columnconfigure(0, weight=1)

        ttk.Label(
            inp,
            text="Вставьте список доменов в любом формате — домены извлекутся автоматически:",
            foreground="gray",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.checker_input = scrolledtext.ScrolledText(inp, height=8, font=("Consolas", 9))
        self.checker_input.grid(row=1, column=0, sticky="nsew")

        # Controls
        ctrl = ttk.Frame(parent)
        ctrl.grid(row=1, column=0, sticky="ew", padx=8, pady=4)

        self.checker_count_lbl = ttk.Label(ctrl, text="", foreground="gray")
        self.checker_count_lbl.pack(side="left", padx=(0, 12))

        ttk.Button(ctrl, text="🔍 Извлечь домены", command=self._checker_preview).pack(side="left", padx=(0, 8))

        ttk.Label(ctrl, text="Потоков:").pack(side="left")
        self.checker_threads = ttk.Spinbox(ctrl, from_=1, to=50, width=5)
        self.checker_threads.set("10")
        self.checker_threads.pack(side="left", padx=(3, 12))

        self.checker_start_btn = ttk.Button(ctrl, text="▶ Проверить", command=self._checker_start)
        self.checker_start_btn.pack(side="left", padx=(0, 4))

        self.checker_stop_btn = ttk.Button(ctrl, text="■ Стоп", command=self._checker_stop, state="disabled")
        self.checker_stop_btn.pack(side="left")

        self.checker_progress = ttk.Progressbar(parent, mode="determinate")
        self.checker_progress.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 2))

        # Results
        res = ttk.LabelFrame(parent, text="Результаты", padding=5)
        res.grid(row=3, column=0, sticky="nsew", padx=8, pady=(4, 2))
        res.rowconfigure(0, weight=1)
        res.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=2)

        self.checker_results = scrolledtext.ScrolledText(
            res, state="disabled", font=("Consolas", 9), height=10)
        self.checker_results.grid(row=0, column=0, sticky="nsew")
        self.checker_results.tag_config("ok", foreground="#1a8a1a")
        self.checker_results.tag_config("err", foreground="#cc0000")
        self.checker_results.tag_config("warn", foreground="#cc7700")

        copy_row = ttk.Frame(parent)
        copy_row.grid(row=4, column=0, sticky="ew", padx=8, pady=(2, 8))
        ttk.Button(copy_row, text="Копировать рабочие", command=self._checker_copy_ok).pack(side="left", padx=(0, 6))
        ttk.Button(copy_row, text="Сохранить рабочие в файл", command=self._checker_save_ok).pack(side="left")
        ttk.Button(copy_row, text="Очистить", command=self._checker_clear).pack(side="right")

        self._checker_ok: list[str] = []
        self._checker_stop_event = threading.Event()

    def _checker_log(self, msg: str, tag: str = ""):
        def _append():
            self.checker_results.config(state="normal")
            self.checker_results.insert("end", msg + "\n", tag)
            self.checker_results.see("end")
            self.checker_results.config(state="disabled")
        self.after(0, _append)

    def _checker_preview(self):
        text = self.checker_input.get("1.0", "end")
        domains = extract_domains(text)
        self.checker_count_lbl.config(text=f"Найдено доменов: {len(domains)}")
        self._checker_log(f"--- Извлечено {len(domains)} доменов ---")
        for d in domains:
            self._checker_log(f"  {d}")

    def _checker_start(self):
        text = self.checker_input.get("1.0", "end")
        domains = extract_domains(text)
        if not domains:
            messagebox.showwarning("Нет доменов", "Домены не найдены в тексте")
            return

        self._checker_ok = []
        self._checker_stop_event.clear()
        self.checker_start_btn.config(state="disabled")
        self.checker_stop_btn.config(state="normal")
        self.checker_progress.config(maximum=len(domains), value=0)
        self._checker_log(f"--- Проверяю {len(domains)} доменов ---")

        threads = int(self.checker_threads.get())
        q: queue.Queue = queue.Queue()
        for d in domains:
            q.put(d)

        self._checker_done_count = 0
        self._checker_total = len(domains)
        self._checker_active = threads
        self._checker_lock = threading.Lock()

        for _ in range(min(threads, len(domains))):
            threading.Thread(
                target=self._checker_worker,
                args=(q,),
                daemon=True,
            ).start()

    def _checker_worker(self, q: queue.Queue):
        while not self._checker_stop_event.is_set():
            try:
                domain = q.get_nowait()
            except queue.Empty:
                break
            tag, msg = self._check_xmlrpc(domain)
            self._checker_log(f"{domain:<40} {msg}", tag)
            if tag == "ok":
                with self._checker_lock:
                    self._checker_ok.append(domain)
            with self._checker_lock:
                self._checker_done_count += 1
                done = self._checker_done_count
            self.after(0, lambda v=done: self.checker_progress.config(value=v))
            q.task_done()

        with self._checker_lock:
            self._checker_active -= 1
            last = self._checker_active == 0
        if last:
            self.after(0, self._checker_finish)

    def _check_xmlrpc(self, domain: str) -> tuple[str, str]:
        for proto in ("https", "http"):
            if self._checker_stop_event.is_set():
                return "warn", "Остановлено"
            url = f"{proto}://{domain}/xmlrpc.php"
            try:
                resp = requests.get(
                    url, timeout=8, allow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                body = resp.text
                if resp.status_code in (200, 405) and (
                    "XML-RPC" in body or "xmlrpc" in body.lower() or resp.status_code == 405
                ):
                    return "ok", f"✓ Включён ({proto.upper()})"
                if resp.status_code == 403:
                    return "warn", "⚠ Заблокирован (403)"
                if resp.status_code == 404:
                    return "err", "✗ Не найден (404)"
                return "warn", f"? Статус {resp.status_code}"
            except requests.exceptions.SSLError:
                if proto == "https":
                    continue
                return "err", "✗ SSL ошибка"
            except requests.exceptions.ConnectionError:
                if proto == "https":
                    continue
                return "err", "✗ Нет соединения"
            except requests.exceptions.Timeout:
                return "err", "✗ Таймаут"
            except Exception as e:
                if proto == "https":
                    continue
                return "err", f"✗ {str(e)[:60]}"
        return "err", "✗ Недоступен"

    def _checker_finish(self):
        total = self._checker_total
        ok = len(self._checker_ok)
        self._checker_log(f"--- Готово: {ok} рабочих из {total} ---")
        self.checker_start_btn.config(state="normal")
        self.checker_stop_btn.config(state="disabled")

    def _checker_stop(self):
        self._checker_stop_event.set()
        self._checker_log("Остановлено пользователем", "warn")
        self.checker_start_btn.config(state="normal")
        self.checker_stop_btn.config(state="disabled")

    def _checker_copy_ok(self):
        if not self._checker_ok:
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(self._checker_ok))

    def _checker_save_ok(self):
        if not self._checker_ok:
            messagebox.showinfo("Пусто", "Нет рабочих доменов")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile="xmlrpc_ok.txt",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._checker_ok))

    def _checker_clear(self):
        self.checker_results.config(state="normal")
        self.checker_results.delete("1.0", "end")
        self.checker_results.config(state="disabled")
        self._checker_ok = []
        self.checker_progress.config(value=0)
        self.checker_count_lbl.config(text="")

    def _update_progress(self, done: int, total: int):
        self.progress_lbl.config(text=f"{done} / {total} постов")
