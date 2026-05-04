DARK: dict = {
    "name": "dark",
    # Backgrounds
    "bg_window":      "#1e1e1e",
    "bg_widget":      "#2b2b2b",
    "bg_plot":        "#2b2b2b",
    "bg_zerospan":    "#1a1a2e",
    "bg_input":       "#333333",
    "bg_panel":       "rgba(40, 40, 40, 200)",
    "bg_table":       "#252525",
    "bg_table_alt":   "#2d2d2d",
    "bg_header":      "#333333",
    "bg_progress":    "#333333",
    "bg_instruction": "#2b2b2b",
    # Borders / separators
    "border":         "#444444",
    "border_input":   "#555555",
    "sep":            "#555555",
    # Text
    "text":           "#e0e0e0",
    "text_dim":       "#cccccc",
    "text_muted":     "#aaaaaa",
    "text_off":       "#888888",
    "text_axis":      "#ffffff",
    "text_axis_dim":  "#cccccc",
    # Buttons (regular toolbar buttons)
    "btn_bg":         "#555555",
    "btn_hover":      "#777777",
    "btn_fg":         "white",
    "btn_fg_off":     "#aaaaaa",
    # Expert panel buttons
    "expert_btn_bg":       "#3a3a3a",
    "expert_btn_fg":       "#e0e0e0",
    "expert_btn_bdr":      "#555555",
    "expert_btn_hover":    "#505050",
    "expert_btn_dis_bg":   "#2a2a2a",
    "expert_btn_dis_fg":   "#666666",
    # Menu bar
    "mb_bg":     "#2b2b2b",
    "mb_fg":     "#e0e0e0",
    "mb_sel":    "#444444",
    "menu_bg":   "#2b2b2b",
    "menu_sel":  "#3a3a3a",
    "menu_bdr":  "#555555",
    # pyqtgraph axes / legend
    "axis_pen":     "#555555",
    "legend_brush": (50, 50, 50, 200),
    # Special labels
    "remote_title":  "#90CAF9",
    "remote_addr":   "#90CAF9",
    "clients_off":   "#888888",
    "fps_fg":        "#666666",
    "zs_title_fg":   "#e0e0e0",
    "zs_level_fg":   "#4FC3F7",
    "zs_axis_fg":    "#cccccc",
    # ── Цвета кривых на графиках ──────────────────────────────────
    "curve_off":        "#39FF14",           # OFF / Noise-спектр
    "curve_on":         "#FFFF00",           # ON / Test-спектр
    "curve_diff":       "#FF4040",           # разностный спектр
    "curve_live":       "#39FF14",           # Live-кривая
    "curve_live_fill":  (57, 255, 20, 22),   # заливка под Live (RGBA)
    "curve_peak":       "#FF8C00",           # Peak Hold
    "curve_on_a":       "#FFC107",           # сессия A — ON
    "curve_on_b":       "#00BCD4",           # сессия B — ON
    "curve_diff_a":     "#FF5722",           # сессия A — Δ
    "curve_diff_b":     "#AB47BC",           # сессия B — Δ
    # ── Маркерные линии ──────────────────────────────────────────
    "marker_sel":        "#FFFFFF",          # выбранная линия
    "marker_unsel":      "#FF9800",          # обычная метка
    "marker_label_fg":   "#FFFFFF",          # текст подписи
    "marker_label_fill": (40, 40, 40, 210),  # фон подписи (RGBA)
    "panorama_mark":     "#FF9800",          # метка в панораме
    # ── Цвета маркеров ПЭМИН-сигналов ────────────────────────────
    "sig_pending":   (255, 220, 50),         # ожидание верификации
    "sig_bookmark":  (255, 152, 0),          # закладка
    "sig_confirmed": (50,  220, 80),         # подтверждённый ПЭМИН
}

LIGHT: dict = {
    "name": "light",
    # Backgrounds
    "bg_window":      "#f0f0f0",
    "bg_widget":      "#ffffff",
    "bg_plot":        "#ffffff",
    "bg_zerospan":    "#f0f4ff",
    "bg_input":       "#ffffff",
    "bg_panel":       "rgba(230, 230, 230, 210)",
    "bg_table":       "#ffffff",
    "bg_table_alt":   "#f5f5f5",
    "bg_header":      "#e4e4e4",
    "bg_progress":    "#e0e0e0",
    "bg_instruction": "#f8f8f8",
    # Borders / separators
    "border":         "#cccccc",
    "border_input":   "#bbbbbb",
    "sep":            "#bbbbbb",
    # Text
    "text":           "#1a1a1a",
    "text_dim":       "#333333",
    "text_muted":     "#555555",
    "text_off":       "#999999",
    "text_axis":      "#222222",
    "text_axis_dim":  "#444444",
    # Buttons
    "btn_bg":         "#d5d5d5",
    "btn_hover":      "#bebebe",
    "btn_fg":         "#1a1a1a",
    "btn_fg_off":     "#555555",
    # Expert panel buttons
    "expert_btn_bg":       "#e8e8e8",
    "expert_btn_fg":       "#1a1a1a",
    "expert_btn_bdr":      "#bbbbbb",
    "expert_btn_hover":    "#d4d4d4",
    "expert_btn_dis_bg":   "#f0f0f0",
    "expert_btn_dis_fg":   "#aaaaaa",
    # Menu bar
    "mb_bg":     "#e8e8e8",
    "mb_fg":     "#1a1a1a",
    "mb_sel":    "#d0d0d0",
    "menu_bg":   "#f0f0f0",
    "menu_sel":  "#dde8f0",
    "menu_bdr":  "#cccccc",
    # pyqtgraph axes / legend
    "axis_pen":     "#aaaaaa",
    "legend_brush": (245, 245, 245, 210),
    # Special labels
    "remote_title":  "#1565C0",
    "remote_addr":   "#1565C0",
    "clients_off":   "#777777",
    "fps_fg":        "#888888",
    "zs_title_fg":   "#1a1a1a",
    "zs_level_fg":   "#0277BD",
    "zs_axis_fg":    "#333333",
    # ── Цвета кривых на графиках ──────────────────────────────────
    "curve_off":        "#1A7A1A",           # OFF / Noise — тёмно-зелёный
    "curve_on":         "#B8860B",           # ON / Test  — тёмно-янтарный
    "curve_diff":       "#C62828",           # разностный — тёмно-красный
    "curve_live":       "#1A7A1A",           # Live-кривая
    "curve_live_fill":  (26, 122, 26, 45),   # заливка под Live (RGBA)
    "curve_peak":       "#D84315",           # Peak Hold  — тёмно-оранжевый
    "curve_on_a":       "#8B6914",           # сессия A — ON
    "curve_on_b":       "#00838F",           # сессия B — ON
    "curve_diff_a":     "#BF360C",           # сессия A — Δ
    "curve_diff_b":     "#7B1FA2",           # сессия B — Δ
    # ── Маркерные линии ──────────────────────────────────────────
    "marker_sel":        "#1A1A1A",          # выбранная линия (был белый)
    "marker_unsel":      "#E65100",          # обычная метка (тёмно-оранжевый)
    "marker_label_fg":   "#1A1A1A",          # текст подписи
    "marker_label_fill": (230, 230, 230, 200), # фон подписи (RGBA)
    "panorama_mark":     "#E65100",          # метка в панораме
    # ── Цвета маркеров ПЭМИН-сигналов ────────────────────────────
    "sig_pending":   (160, 100,   0),        # тёмно-янтарный
    "sig_bookmark":  (200,  80,   0),        # тёмно-оранжевый
    "sig_confirmed": ( 20, 130,  30),        # тёмно-зелёный
}
