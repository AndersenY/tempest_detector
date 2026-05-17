DARK: dict = {
    "name": "dark",
    # Фоны
    "bg_window":      "#14171c",
    "bg_widget":      "#1a1e26",
    "bg_plot":        "#14171c",
    "bg_zerospan":    "#14171c",
    "bg_input":       "#20242e",
    "bg_panel":       "rgba(26,30,38,220)",
    "bg_table":       "#14171c",
    "bg_table_alt":   "#1a1e26",
    "bg_header":      "#20242e",
    "bg_progress":    "#20242e",
    "bg_instruction": "#1a1e26",
    # Границы и разделители
    "border":         "#2c3140",
    "border_input":   "#393f50",
    "sep":            "#393f50",
    # Текст
    "text":           "#e6e9ef",
    "text_dim":       "#a3a9b7",
    "text_muted":     "#6b7281",
    "text_off":       "#4a5060",
    "text_axis":      "#e6e9ef",
    "text_axis_dim":  "#a3a9b7",
    # Кнопки панели инструментов (наложение на графиках)
    "btn_bg":           "#20242e",
    "btn_hover":        "#2c3140",
    "btn_fg":           "#e6e9ef",
    "btn_fg_off":       "#6b7281",
    "btn_border":       "#2c3140",
    "btn_active":       "#4fb3a0",
    "btn_danger":       "#ef5350",
    "btn_danger_hover": "#e53935",
    # Главная кнопка действия и прогрессбар
    "btn_primary_bg":    "#4fb3a0",
    "btn_primary_hover": "#3d9e8d",
    "progress_chunk":    "#4fb3a0",
    # Кнопки экспертной панели
    "expert_btn_bg":       "#20242e",
    "expert_btn_fg":       "#e6e9ef",
    "expert_btn_bdr":      "#393f50",
    "expert_btn_hover":    "#2c3140",
    "expert_btn_dis_bg":   "#14171c",
    "expert_btn_dis_fg":   "#4a5060",
    # Строка меню
    "mb_bg":     "#1a1e26",
    "mb_fg":     "#e6e9ef",
    "mb_sel":    "#2c3140",
    "menu_bg":   "#1a1e26",
    "menu_sel":  "#20242e",
    "menu_bdr":  "#2c3140",
    # Оси и легенда pyqtgraph
    "axis_pen":     "#2c3140",
    "legend_brush": (26, 30, 38, 200),
    # Специальные метки
    "remote_title":  "#6b7281",
    "remote_addr":   "#4fb3a0",
    "clients_off":   "#4a5060",
    "fps_fg":        "#4a5060",
    "zs_title_fg":   "#e6e9ef",
    "zs_level_fg":   "#4ade80",
    "zs_axis_fg":    "#a3a9b7",
    # ── Цвета кривых на графиках ──────────────────────────────────
    "curve_off":        "#4ade80",           # OFF / Noise-спектр — мятно-зелёный
    "curve_on":         "#ffd54f",           # ON / Test-спектр — янтарный
    "curve_diff":       "#ef5350",           # разностный спектр — красный
    "curve_live":       "#4ade80",           # Live-кривая — мятно-зелёный
    "curve_live_fill":  (74, 222, 128, 28),    # заливка под Live (RGBA)
    "curve_peak":       "#ff8c00",           # удержание пика
    "curve_on_a":       "#FFC107",           # сессия A — ON
    "curve_on_b":       "#00BCD4",           # сессия B — ON
    "curve_diff_a":     "#FF5722",           # сессия A — Δ
    "curve_diff_b":     "#AB47BC",           # сессия B — Δ
    # ── Маркерные линии ──────────────────────────────────────────
    "marker_sel":        "#ffffff",          # выбранная линия
    "marker_unsel":      "#ff9800",          # обычная метка
    "marker_label_fg":   "#e6e9ef",          # текст подписи
    "marker_label_fill": (26, 30, 38, 210),    # фон подписи (RGBA)
    "panorama_mark":     "#ff9800",          # метка в панораме
    # ── Цвета маркеров ПЭМИН-сигналов ────────────────────────────
    "sig_pending":   (255, 183, 77),           # ожидание верификации
    "sig_bookmark":  (255, 152, 0),            # закладка
    "sig_confirmed": (74,  222, 128),          # подтверждённый ПЭМИН — мятно-зелёный
    # ── Цвета статусов в таблице результатов ─────────────────────────────
    "tbl_status_ok":   "#66bb6a",            # ПЭМИН подтверждён
    "tbl_status_fail": "#ef5350",            # Брак (В1)
    "tbl_status_ext":  "#42a5f5",            # Внешний / Двойной брак
    "tbl_status_warn": "#ffca28",            # В1 OK, Потенциальный
    "tbl_status_wait": "#6b7281",            # Ожидание
}

LIGHT: dict = {
    "name": "light",
    # Фоны
    "bg_window":      "#eef1f6",
    "bg_widget":      "#ffffff",
    "bg_plot":        "#ffffff",
    "bg_zerospan":    "#f8faff",
    "bg_input":       "#f8fafc",
    "bg_panel":       "rgba(238,241,246,220)",
    "bg_table":       "#ffffff",
    "bg_table_alt":   "#f3f5f9",
    "bg_header":      "#f3f5f9",
    "bg_progress":    "#dde2eb",
    "bg_instruction": "#ffffff",
    # Границы и разделители
    "border":         "#dde2eb",
    "border_input":   "#cdd5e0",
    "sep":            "#cdd5e0",
    # Текст
    "text":           "#14171c",
    "text_dim":       "#4a5263",
    "text_muted":     "#7d8597",
    "text_off":       "#a0a8b8",
    "text_axis":      "#14171c",
    "text_axis_dim":  "#4a5263",
    # Кнопки панели инструментов
    "btn_bg":           "#f3f5f9",
    "btn_hover":        "#dde2eb",
    "btn_fg":           "#14171c",
    "btn_fg_off":       "#7d8597",
    "btn_border":       "#dde2eb",
    "btn_active":       "#2f9a86",
    "btn_danger":       "#c62828",
    "btn_danger_hover": "#b71c1c",
    # Главная кнопка действия и прогрессбар
    "btn_primary_bg":    "#2f9a86",
    "btn_primary_hover": "#1d7a68",
    "progress_chunk":    "#2f9a86",
    # Кнопки экспертной панели
    "expert_btn_bg":       "#f3f5f9",
    "expert_btn_fg":       "#14171c",
    "expert_btn_bdr":      "#dde2eb",
    "expert_btn_hover":    "#dde2eb",
    "expert_btn_dis_bg":   "#eef1f6",
    "expert_btn_dis_fg":   "#a0a8b8",
    # Строка меню
    "mb_bg":     "#ffffff",
    "mb_fg":     "#14171c",
    "mb_sel":    "#dde2eb",
    "menu_bg":   "#ffffff",
    "menu_sel":  "#f3f5f9",
    "menu_bdr":  "#dde2eb",
    # Оси и легенда pyqtgraph
    "axis_pen":     "#dde2eb",
    "legend_brush": (248, 250, 252, 220),
    # Специальные метки
    "remote_title":  "#7d8597",
    "remote_addr":   "#2f9a86",
    "clients_off":   "#a0a8b8",
    "fps_fg":        "#a0a8b8",
    "zs_title_fg":   "#14171c",
    "zs_level_fg":   "#2e7d32",
    "zs_axis_fg":    "#4a5263",
    # ── Цвета кривых на графиках ──────────────────────────────────
    "curve_off":        "#2e7d32",           # OFF / Noise — тёмно-зелёный (AA на белом)
    "curve_on":         "#b26900",           # ON / Test  — тёмно-янтарный
    "curve_diff":       "#c62828",           # разностный — тёмно-красный
    "curve_live":       "#2e7d32",           # Live-кривая — тёмно-зелёный
    "curve_live_fill":  (46, 125, 50, 40),     # заливка под Live (RGBA)
    "curve_peak":       "#d84315",           # Peak Hold  — тёмно-оранжевый
    "curve_on_a":       "#8B6914",           # сессия A — ON
    "curve_on_b":       "#00838F",           # сессия B — ON
    "curve_diff_a":     "#BF360C",           # сессия A — Δ
    "curve_diff_b":     "#7B1FA2",           # сессия B — Δ
    # ── Маркерные линии ──────────────────────────────────────────
    "marker_sel":        "#14171c",          # выбранная линия
    "marker_unsel":      "#e65100",          # обычная метка
    "marker_label_fg":   "#14171c",          # текст подписи
    "marker_label_fill": (238, 241, 246, 210), # фон подписи (RGBA)
    "panorama_mark":     "#e65100",          # метка в панораме
    # ── Цвета маркеров ПЭМИН-сигналов ────────────────────────────
    "sig_pending":   (180, 100,   0),          # тёмно-янтарный
    "sig_bookmark":  (200,  80,   0),          # тёмно-оранжевый
    "sig_confirmed": ( 46, 125,  50),           # тёмно-зелёный
    # ── Цвета статусов в таблице результатов ─────────────────────────────
    "tbl_status_ok":   "#2e7d32",            # ПЭМИН подтверждён  — тёмно-зелёный
    "tbl_status_fail": "#c62828",            # Брак (В1)          — тёмно-красный
    "tbl_status_ext":  "#1565c0",            # Внешний            — тёмно-синий
    "tbl_status_warn": "#e65100",            # В1 OK / Потенц.    — тёмно-оранжевый
    "tbl_status_wait": "#7d8597",            # Ожидание           — средне-серый
}


# ---------------------------------------------------------------------------
# Вспомогательные функции для стилей кнопок (overlay-панели на графиках)
# ---------------------------------------------------------------------------

def btn_normal(t: dict) -> str:
    """Обычная кнопка (не переключатель). Используется в overlay-панели на графиках."""
    return (
        f"QPushButton {{ background-color: {t['btn_bg']}; color: {t['btn_fg']};"
        f" border: 1px solid {t['btn_border']}; border-radius: 4px;"
        f" font-size: 11px; min-height: 22px; padding: 3px 12px; }}"
        # hover: фон делаем на шаг темнее панели — заметнее чем btn_hover
        f" QPushButton:hover {{ background-color: {t['border']};"
        f" color: {t['text']}; border-color: {t['border_input']}; }}"
        f" QPushButton:disabled {{ background-color: {t['bg_input']};"
        f" color: {t['text_off']}; border-color: {t['btn_border']}; }}"
    )


def btn_toggle(t: dict) -> str:
    """Кнопка-переключатель. Активное состояние = акцентный цвет."""
    return (
        f"QPushButton {{ background-color: {t['btn_bg']}; color: {t['btn_fg_off']};"
        f" border: 1px solid {t['btn_border']}; border-radius: 4px;"
        f" font-size: 11px; min-height: 22px; padding: 3px 12px; }}"
        f" QPushButton:checked {{ background-color: {t['btn_active']};"
        f" color: #ffffff; border-color: {t['btn_active']}; }}"
        f" QPushButton:hover {{ background-color: {t['border']};"
        f" color: {t['text']}; border-color: {t['border_input']}; }}"
        # hover поверх checked — акцент остаётся, чуть светлее
        f" QPushButton:checked:hover {{ background-color: {t['btn_primary_hover']};"
        f" color: #ffffff; }}"
        f" QPushButton:disabled {{ background-color: {t['bg_input']};"
        f" color: {t['text_off']}; border-color: {t['btn_border']}; }}"
    )


def btn_icon(t: dict, checkable: bool = False) -> str:
    """Иконочная кнопка фикс. размера (28×28)."""
    s = (
        f"QPushButton {{ background-color: {t['btn_bg']}; color: {t['btn_fg']};"
        f" border: 1px solid {t['btn_border']}; border-radius: 4px;"
        f" font-size: 13px; padding: 2px; }}"
        f" QPushButton:hover {{ background-color: {t['border']};"
        f" color: {t['text']}; border-color: {t['border_input']}; }}"
    )
    if checkable:
        s += (
            f" QPushButton:checked {{ background-color: {t['btn_active']};"
            f" color: #ffffff; border-color: {t['btn_active']}; }}"
            f" QPushButton:checked:hover {{ background-color: {t['btn_primary_hover']}; }}"
        )
    return s


def btn_primary(t: dict, large: bool = True) -> str:
    """Главная кнопка действия (Подключить и начать / Запустить верификацию / Пауза).

    large=True  — крупная для action-bar (padding 8x16, font 13).
    large=False — компактная для panel-внутри (padding 5x12, font 12).
    """
    pad    = "8px 16px" if large else "5px 12px"
    font   = "13px"     if large else "12px"
    min_h  = "34px"     if large else "26px"
    return (
        f"QPushButton {{ background-color: {t['btn_primary_bg']}; color: white;"
        f" border: none; border-radius: 4px; font-size: {font};"
        f" font-weight: 600; padding: {pad}; min-height: {min_h}; }}"
        f" QPushButton:hover {{ background-color: {t['btn_primary_hover']}; }}"
        f" QPushButton:pressed {{ background-color: {t['btn_primary_hover']};"
        f" padding-top: 9px; padding-bottom: 7px; }}"
        f" QPushButton:disabled {{ background-color: {t['btn_bg']};"
        f" color: {t['text_off']}; }}"
    )


def btn_danger(t: dict, large: bool = False) -> str:
    """Кнопка деструктивного действия (Сброс, удалить).

    large=True — для action-bar (как btn_primary, но красная).
    """
    pad    = "8px 16px" if large else "4px 12px"
    font   = "13px"     if large else "12px"
    min_h  = "34px"     if large else "26px"
    weight = "600"      if large else "500"
    return (
        f"QPushButton {{ background-color: {t['btn_danger']}; color: #ffffff;"
        f" border: none; border-radius: 4px; font-size: {font};"
        f" font-weight: {weight}; padding: {pad}; min-height: {min_h}; }}"
        f" QPushButton:hover {{ background-color: {t['btn_danger_hover']}; }}"
        f" QPushButton:pressed {{ background-color: {t['btn_danger_hover']};"
        f" padding-top: 9px; padding-bottom: 7px; }}"
        f" QPushButton:disabled {{ background-color: {t['btn_bg']};"
        f" color: {t['text_off']}; }}"
    )
