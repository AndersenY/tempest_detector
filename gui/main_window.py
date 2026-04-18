from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTableWidget, QTableWidgetItem, QLabel, QProgressBar, QMessageBox, QGroupBox, QHeaderView)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from .spectrum_widget import SpectrumPlotWidget
from core.workflow import MeasurementWorkflow
from core.config import PanoramaConfig
from core.sdr_controller import SDRController

class Worker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(float)
    data = pyqtSignal(object, object, object)
    action_needed = pyqtSignal(str, str, str) # Title, Instruction, ButtonText
    error = pyqtSignal(str)

    def __init__(self, workflow: MeasurementWorkflow):
        super().__init__()
        self.wf = workflow
        self.wf.on_status = self.status.emit
        self.wf.on_progress = self.progress.emit
        self.wf.on_data = lambda a,b,c: self.data.emit(a,b,c)
        self.wf.on_user_action_needed = self.action_needed.emit

    def run(self):
        self.wf.run_discovery_phase_1()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ПЭМИН Навигатор (RTL-SDR)")
        self.resize(1200, 800)
        
        # Глобальный стиль приложения для комфорта глаз
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                color: #e0e0e0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)

        self.cfg = PanoramaConfig()
        self.ctrl = SDRController()
        self.wf = None
        self.thread = None
        self.current_step = "idle" 

        self._init_ui()

    def _init_ui(self):
        w = QWidget()
        self.setCentralWidget(w)
        main_layout = QVBoxLayout(w)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 1. Прогресс бар
        self.prog = QProgressBar()
        self.prog.setTextVisible(True)
        self.prog.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
                color: white;
                background-color: #333;
            }
            QProgressBar::chunk {
                background-color: #2196F3;
                width: 10px;
                margin: 0.5px;
            }
        """)
        main_layout.addWidget(self.prog)

        # 2. График
        self.plot = SpectrumPlotWidget()
        main_layout.addWidget(self.plot, 3)

        # 3. Нижняя секция: Таблица (слева) и Управление (справа)
        bottom_section = QHBoxLayout()
        bottom_section.setSpacing(10)
        
        # --- ЛЕВАЯ КОЛОНКА: Таблица ---
        table_group = QGroupBox("Результаты измерений")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(5, 5, 5, 5)
        
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Частота (МГц)", "Δ дБ", "ON дБ", "OFF дБ", "Тип", "Статус"])
        
        # ВАЖНО: Растягиваем колонки по ширине
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        # Стиль таблицы для комфортного чтения
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #252525;
                alternate-background-color: #2d2d2d; /* Чередование строк */
                color: #e0e0e0;
                gridline-color: #444;
                border: 1px solid #444;
            }
            QHeaderView::section {
                background-color: #333;
                color: #fff;
                padding: 4px;
                border: 1px solid #444;
                font-weight: bold;
            }
            QTableWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
        """)
        self.table.setAlternatingRowColors(True) # Включаем зебру
        
        table_layout.addWidget(self.table)
        
        bottom_section.addWidget(table_group, 2) # Коэффициент 2

        # --- ПРАВАЯ КОЛОНКА: Управление ---
        control_group = QGroupBox("Статус и Управление")
        control_layout = QVBoxLayout(control_group)
        control_layout.setContentsMargins(10, 10, 10, 10)
        control_layout.setSpacing(10)
        
        # Текст инструкции (теперь на мягком сером фоне)
        self.lbl_instruction = QLabel("Подключите SDR для начала работы.")
        self.lbl_instruction.setStyleSheet("""
            QLabel {
                color: #e0e0e0; 
                font-size: 13px; 
                padding: 10px; 
                background-color: #2b2b2b; 
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        self.lbl_instruction.setWordWrap(True)
        self.lbl_instruction.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_instruction.setMinimumHeight(100)
        
        control_layout.addWidget(self.lbl_instruction)
        control_layout.addStretch(1)

        # Главная кнопка действия
        self.btn_action = QPushButton("ПОДКЛЮЧИТЬ И НАЧАТЬ")
        self.btn_action.setStyleSheet("""
            QPushButton {
                background-color: #2196F3; 
                color: white; 
                font-weight: bold;
                padding: 12px; 
                border-radius: 4px; 
                font-size: 14px;
                border: none;
            }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:pressed { background-color: #0D47A1; }
            QPushButton:disabled { 
                background-color: #444; 
                color: #888; 
            }
        """)
        self.btn_action.clicked.connect(self._on_control_button_clicked)
        control_layout.addWidget(self.btn_action)

        bottom_section.addWidget(control_group, 1) # Коэффициент 1

        main_layout.addLayout(bottom_section, 2)

    def _on_control_button_clicked(self):
        if self.current_step == "idle":
            self._connect_and_start()
        elif self.current_step == "measure_on":
            self._run_next_step(self.wf.run_discovery_phase_2)
        elif self.current_step == "verify_1":
            self._run_next_step(self.wf.run_verification_1)
        elif self.current_step == "verify_2":
            self._run_next_step(self.wf.run_verification_2)
        elif self.current_step == "finish":
            self._reset_all()

    def _connect_and_start(self):
        try:
            self.ctrl.connect()
            self.ctrl.configure(self.cfg)
            self._start_workflow()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _start_workflow(self):
        self.current_step = "measure_off"
        self.lbl_instruction.setText("⏳ <b>Измерение фона...</b><br>Пожалуйста, подождите.")
        self.btn_action.setEnabled(False)
        self.prog.setValue(0)
        self.table.setRowCount(0)
        self.plot.clear()
        
        self.wf = MeasurementWorkflow(self.ctrl, self.cfg)
        self.thread = Worker(self.wf)
        
        self.thread.status.connect(lambda s: None) 
        self.thread.progress.connect(lambda v: self.prog.setValue(int(v)))
        self.thread.data.connect(self._plot_data)
        self.thread.action_needed.connect(self._on_action_needed)
        self.thread.error.connect(lambda e: QMessageBox.critical(self, "Ошибка", e))
        
        self.thread.start()

    def _on_action_needed(self, title, instruction, btn_text):
        if "ИЗМЕРИТЬ СИГНАЛ" in btn_text:
            self.current_step = "measure_on"
        elif "ВЕРИФИКАЦИЮ 1" in btn_text:
            self.current_step = "verify_1"
        elif "ВЕРИФИКАЦИЮ 2" in btn_text:
            self.current_step = "verify_2"
        elif "СБРОС" in btn_text or "ЗАВЕРШЕНА" in title:
            self.current_step = "finish"
            
        # HTML форматирование для заголовка и текста
        color = "#4CAF50" if self.current_step == "finish" else "#FF9800"
        html_text = f"<h3 style='color: {color}; margin-bottom: 5px;'>{title}</h3>"
        html_text += f"<div style='line-height: 1.4;'>{instruction.replace(chr(10), '<br>')}</div>"
        
        self.lbl_instruction.setText(html_text)
        self.btn_action.setText(btn_text)
        self.btn_action.setEnabled(True)
        
        if self.current_step == "finish":
            self.btn_action.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 12px; border-radius: 4px; font-size: 14px; border: none; } QPushButton:hover { background-color: #388E3C; }")
        else:
            self.btn_action.setStyleSheet("QPushButton { background-color: #FF9800; color: white; font-weight: bold; padding: 12px; border-radius: 4px; font-size: 14px; border: none; } QPushButton:hover { background-color: #F57C00; }")

    def _run_next_step(self, step_func):
        self.lbl_instruction.setText("⏳ <b>Выполнение измерения...</b>")
        self.btn_action.setEnabled(False)
        
        class StepWorker(QThread):
            def __init__(self, func):
                super().__init__()
                self.func = func
            def run(self):
                self.func()
                
        self.step_worker = StepWorker(step_func)
        self.step_worker.status = self.thread.status
        self.step_worker.progress = self.thread.progress
        self.step_worker.action_needed = self.thread.action_needed
        self.step_worker.error = self.thread.error
        
        self.step_worker.status.connect(lambda s: None)
        self.step_worker.progress.connect(lambda v: self.prog.setValue(int(v)))
        self.step_worker.action_needed.connect(self._on_action_needed)
        self.step_worker.error.connect(lambda e: QMessageBox.critical(self, "Ошибка", e))
        
        self.step_worker.start()

    def _reset_all(self):
        self.current_step = "idle"
        self.prog.setValue(0)
        self.table.setRowCount(0)
        self.plot.clear()
        self.lbl_instruction.setText("<b>Работа завершена.</b><br>Нажмите для нового цикла.")
        self.btn_action.setText("НАЧАТЬ НОВЫЙ ПОИСК")
        self.btn_action.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; padding: 12px; border-radius: 4px; font-size: 14px; border: none; } QPushButton:hover { background-color: #1976D2; }")

    def _plot_data(self, on, off, diff):
        f_mhz = on.frequencies_hz / 1e6
        self.plot.clear()
        self.plot.add('ON (Test)', f_mhz, on.amplitudes_db, 'y')
        self.plot.add('OFF (Noise)', f_mhz, off.amplitudes_db, 'b')
        self.plot.add('Difference', f_mhz, diff, 'r', fill=(255,0,0,50))
        self.plot.set_threshold(self.cfg.threshold_db)
        
        signals = self.wf.signals if self.wf else []
        self.table.setRowCount(len(signals))
        for i, s in enumerate(signals):
            self.table.setItem(i, 0, QTableWidgetItem(f"{s.frequency_hz/1e6:.4f}"))
            self.table.setItem(i, 1, QTableWidgetItem(f"{s.amplitude_diff_db:.1f}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{s.amplitude_on_db:.1f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{s.amplitude_off_db:.1f}"))
            self.table.setItem(i, 4, QTableWidgetItem("Тройка" if s.is_triplet_representative else "Точка"))
            st = []
            if s.verified_1 is False: st.append("❌В1")
            if s.verified_2 is False: st.append("❌В2")
            if not st: st.append("✅ OK")
            self.table.setItem(i, 5, QTableWidgetItem(" ".join(st)))
        
        self.plot.plot_signals(signals)
        self.plot.reset_zoom() 