import sys
import csv
import os
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTableWidget, QTableWidgetItem, QLabel, 
                             QProgressBar, QMessageBox, QGroupBox, QHeaderView, QApplication, QFileDialog)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QCoreApplication
from core.workflow import MeasurementWorkflow
from core.config import PanoramaConfig
from core.sdr_controller import SDRController
from gui.spectrum_widget import SpectrumPlotWidget

class Worker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(float)
    data = pyqtSignal(object, object, object)
    action_needed = pyqtSignal(str, str, str)
    error = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, workflow: MeasurementWorkflow):
        super().__init__()
        self.wf = workflow
        self.wf.on_status = self.status.emit
        self.wf.on_progress = self.progress.emit
        self.wf.on_data = lambda a, b, c: self.data.emit(a, b, c)
        self.wf.on_user_action_needed = self.action_needed.emit

    def run(self):
        try:
            self.wf.run_full_cycle()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished_signal.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ПЭМИН Навигатор (RTL-SDR)")
        self.resize(1200, 800)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QGroupBox { font-weight: bold; border: 1px solid #444; border-radius: 5px; margin-top: 10px; padding-top: 10px; color: #e0e0e0; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }
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

        # 1. Top Control Panel
        top_control_layout = QHBoxLayout()
        
        self.prog = QProgressBar()
        self.prog.setTextVisible(True)
        self.prog.setStyleSheet("""
            QProgressBar { border: 1px solid #444; border-radius: 4px; text-align: center; color: white; background-color: #333; }
            QProgressBar::chunk { background-color: #2196F3; width: 10px; margin: 0.5px; }
        """)
        
        self.btn_stop = QPushButton("⛔ СТОП")
        self.btn_stop.setStyleSheet("""
            QPushButton { background-color: #D32F2F; color: white; font-weight: bold; padding: 5px 15px; border-radius: 4px; }
            QPushButton:hover { background-color: #B71C1C; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_process)
        
        top_control_layout.addWidget(self.prog, 1)
        top_control_layout.addWidget(self.btn_stop)
        main_layout.addLayout(top_control_layout)

        # 2. Spectrum Plot
        self.plot = SpectrumPlotWidget()
        main_layout.addWidget(self.plot, 3)

        # 3. Bottom Section
        bottom_section = QHBoxLayout()
        bottom_section.setSpacing(10)
        
        # --- LEFT COLUMN: Results Table ---
        table_group = QGroupBox("Результаты измерений")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(5, 5, 5, 5)
        
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Частота (МГц)", "Δ дБ", "ON дБ", "OFF дБ", "Тип", "Статус"])
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #252525; alternate-background-color: #2d2d2d; color: #e0e0e0; gridline-color: #444; border: 1px solid #444; }
            QHeaderView::section { background-color: #333; color: #fff; padding: 4px; border: 1px solid #444; font-weight: bold; }
            QTableWidget::item:selected { background-color: #2196F3; color: white; }
        """)
        
        table_layout.addWidget(self.table)
        bottom_section.addWidget(table_group, 2)

        # --- RIGHT COLUMN: Status and Action ---
        control_group = QGroupBox("Статус и Управление")
        control_layout = QVBoxLayout(control_group)
        control_layout.setContentsMargins(10, 10, 10, 10)
        control_layout.setSpacing(10)
        
        self.lbl_instruction = QLabel("Подключите SDR для начала работы.")
        self.lbl_instruction.setStyleSheet("color: #e0e0e0; font-size: 13px; padding: 10px; background-color: #2b2b2b; border: 1px solid #444; border-radius: 4px;")
        self.lbl_instruction.setWordWrap(True)
        self.lbl_instruction.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_instruction.setMinimumHeight(100)
        
        control_layout.addWidget(self.lbl_instruction)
        
        # Кнопка сохранения отчета
        self.btn_save = QPushButton("💾 Сохранить отчет (CSV)")
        self.btn_save.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; border-radius: 4px; font-size: 12px; border: none; }
            QPushButton:hover { background-color: #388E3C; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_report)
        control_layout.addWidget(self.btn_save)

        control_layout.addStretch(1)

        self.btn_action = QPushButton("ПОДКЛЮЧИТЬ И НАЧАТЬ")
        self.btn_action.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; font-weight: bold; padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled { background-color: #444; color: #888; }
        """)
        self.btn_action.clicked.connect(self._on_control_button_clicked)
        control_layout.addWidget(self.btn_action)

        bottom_section.addWidget(control_group, 1)
        main_layout.addLayout(bottom_section, 2)

    def _save_report(self):
        """Сохраняет текущие данные таблицы в CSV файл"""
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "Внимание", "Нет данных для сохранения.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"pemin_report_{timestamp}.csv"
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчет", default_name, "CSV Files (*.csv)")
        
        if file_path:
            try:
                with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    # Заголовки
                    headers = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
                    writer.writerow(headers)
                    
                    # Данные
                    for row in range(self.table.rowCount()):
                        row_data = []
                        for col in range(self.table.columnCount()):
                            item = self.table.item(row, col)
                            row_data.append(item.text() if item else "")
                        writer.writerow(row_data)
                
                QMessageBox.information(self, "Успех", f"Отчет сохранен:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{str(e)}")

    def _stop_process(self):
        if self.thread and self.thread.isRunning():
            if self.wf:
                self.wf.stop()
            self.btn_stop.setEnabled(False)
            self.lbl_instruction.setText("<b style='color: orange;'>Остановка...</b>")
            self.btn_action.setEnabled(False)

    def _on_control_button_clicked(self):
        if self.current_step == "idle":
            self._connect_and_start()
        else:
            if self.wf:
                self.wf.resume()
                self.btn_action.setEnabled(False)
                self.lbl_instruction.setText("⏳ Выполнение измерения...")
                self.btn_stop.setEnabled(True)

    def _connect_and_start(self):
        try:
            self.ctrl.connect()
            self.ctrl.configure(self.cfg)
            self._start_workflow()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка подключения", str(e))

    def _start_workflow(self):
        self.current_step = "running"
        self.lbl_instruction.setText("⏳ <b>Запуск процесса...</b>")
        self.btn_action.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_save.setEnabled(False)
        self.prog.setValue(0)
        
        # Очищаем таблицу и график при старте
        self.table.setRowCount(0)
        self.plot.clear()
        
        self.wf = MeasurementWorkflow(self.ctrl, self.cfg)
        self.thread = Worker(self.wf)
        
        self.thread.status.connect(lambda s: self.lbl_instruction.setText(s)) 
        self.thread.progress.connect(lambda v: self.prog.setValue(int(v)))
        self.thread.data.connect(self._plot_data)
        self.thread.action_needed.connect(self._on_action_needed)
        self.thread.error.connect(lambda e: QMessageBox.critical(self, "Ошибка", e))
        self.thread.finished_signal.connect(self._on_thread_finished)
        
        self.thread.start()

    def _on_action_needed(self, title, instruction, btn_text):
        self.current_step = "waiting"
        
        color = "#FF9800"
        if "ЗАВЕРШЕНА" in title or "ЗАВЕРШЕНО" in title:
            color = "#4CAF50"
        elif "ОШИБКА" in title or "СТОП" in title:
            color = "#F44336"
            
        html_text = f"<h3 style='color: {color}; margin-bottom: 5px;'>{title}</h3>"
        html_text += f"<div style='line-height: 1.4;'>{instruction.replace(chr(10), '<br>')}</div>"
        
        self.lbl_instruction.setText(html_text)
        self.btn_action.setText(btn_text)
        self.btn_action.setEnabled(True)
        self.btn_stop.setEnabled(False)
        
        if "ЗАВЕРШЕНА" in title or "ЗАВЕРШЕНО" in title:
             self.btn_action.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 12px; border-radius: 4px; font-size: 14px; border: none; } QPushButton:hover { background-color: #388E3C; }")
             self.btn_save.setEnabled(True) # Разрешаем сохранение после завершения
        else:
             self.btn_action.setStyleSheet("QPushButton { background-color: #FF9800; color: white; font-weight: bold; padding: 12px; border-radius: 4px; font-size: 14px; border: none; } QPushButton:hover { background-color: #F57C00; }")
        
        # Если есть сигналы, обновляем таблицу финальными данными
        if self.wf and hasattr(self.wf, 'signals'):
            self._update_table_only()

    def _on_thread_finished(self):
        self.btn_stop.setEnabled(False)
        self.current_step = "idle"
        self.btn_action.setText("НОВЫЙ ПОИСК")
        self.btn_action.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; font-weight: bold; padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
            QPushButton:hover { background-color: #1976D2; }
        """)

    def _plot_data(self, on, off, diff):
        """
        Вызывается после этапа обнаружения. Обновляет график и таблицу кандидатов.
        """
        f_mhz = on.frequencies_hz / 1e6
        self.plot.clear()
        self.plot.add('ON (Test)', f_mhz, on.amplitudes_db, 'y')
        self.plot.add('OFF (Noise)', f_mhz, off.amplitudes_db, 'b')
        self.plot.add('Difference', f_mhz, diff, 'r', fill=(255,0,0,50))
        self.plot.set_threshold(self.cfg.threshold_db)
        
        # Обновляем таблицу
        if self.wf and hasattr(self.wf, 'signals'):
            signals = self.wf.signals
            self._update_table_from_signals(signals)
            
            self.plot.plot_signals(signals)
            self.plot.reset_zoom() 
        else:
            print("Warning: Workflow or signals not available for table update.")

    def _update_table_only(self):
        """Обновляет только таблицу (используется после верификации)"""
        if self.wf and hasattr(self.wf, 'signals'):
            self._update_table_from_signals(self.wf.signals)

    def _update_table_from_signals(self, signals):
        """
        Оптимизированное обновление таблицы с приятной цветовой палитрой.
        """
        # 1. Отключаем сортировку и перерисовку для скорости
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        
        count = len(signals)
        self.table.setRowCount(count)
        
        if count == 0:
            self.table.setUpdatesEnabled(True)
            self.table.repaint()
            return

        # Определение цветов (Hex коды для мягкой палитры в темной теме)
        COLOR_WAIT = "#9E9E9E"      # Серый
        COLOR_SUCCESS = "#66BB6A"   # Мягкий зеленый (ПЭМИН)
        COLOR_FAIL_V1 = "#EF5350"   # Мягкий красный (Не прошел В1)
        COLOR_FAIL_V2 = "#42A5F5"   # Мягкий синий (Не прошел В2 / Внешний)
        COLOR_WARN = "#FFCA28"      # Янтарный (Промежуточный статус)

        for i, s in enumerate(signals):
            # --- Данные ---
            item_freq = QTableWidgetItem(f"{s.frequency_hz/1e6:.4f}")
            item_diff = QTableWidgetItem(f"{s.amplitude_diff_db:.1f}")
            item_on = QTableWidgetItem(f"{s.amplitude_on_db:.1f}")
            item_off = QTableWidgetItem(f"{s.amplitude_off_db:.1f}")
            item_type = QTableWidgetItem("Тройка" if s.is_triplet_representative else "Точка")
            
            # --- Логика Статусов и Цветов ---
            status_text = "⏳ Ожидание"
            color_hex = COLOR_WAIT
            
            v1 = s.verified_1
            v2 = s.verified_2

            if v1 is None and v2 is None:
                status_text = "⏳ Ожидание"
                color_hex = COLOR_WAIT
            
            elif v1 is not None and v2 is None:
                # Промежуточный этап (после В1, до В2)
                if v1:
                    status_text = "✅ В1 OK"
                    color_hex = COLOR_WARN # Желтый, так как еще не финал
                else:
                    status_text = "❌ В1 (Помеха)"
                    color_hex = COLOR_FAIL_V1
            
            elif v1 is not None and v2 is not None:
                # Финальный этап
                if v1 and v2:
                    status_text = "✅ ПЭМИН"
                    color_hex = COLOR_SUCCESS
                elif not v1:
                    # Если не прошел В1, то В2 уже не так важен, но покажем общий брак
                    status_text = "❌ Брак (В1)"
                    color_hex = COLOR_FAIL_V1
                elif v1 and not v2:
                    status_text = "❌ Фон (В2)"
                    color_hex = COLOR_FAIL_V2

            item_status = QTableWidgetItem(status_text)
            
            # Применяем цвет к тексту
            from PyQt6.QtGui import QColor
            item_status.setForeground(QColor(color_hex))
            
            # Можно также слегка подсветить фон ячейки для лучшей читаемости (опционально)
            # item_status.setBackground(QColor(color_hex).darker(150)) 

            # Установка элементов
            self.table.setItem(i, 0, item_freq)
            self.table.setItem(i, 1, item_diff)
            self.table.setItem(i, 2, item_on)
            self.table.setItem(i, 3, item_off)
            self.table.setItem(i, 4, item_type)
            self.table.setItem(i, 5, item_status)

        # 4. Включаем обновление
        self.table.setUpdatesEnabled(True)
        self.table.setSortingEnabled(True)
        self.table.repaint()
        # Обработка событий интерфейса
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())