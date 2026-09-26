import sys
import time
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
import serial

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QSpinBox, QGroupBox,
    QCheckBox, QComboBox
)

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)

import threading
from flask import Flask, render_template_string, Response
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvasAgg
import io
import base64

# 備註：
# 總資料空間2560筆，資料累積上限1000筆，每50ms抓11筆資料，不足就做zero padding
# 空間設2560筆 -> 頻譜顯示更平滑

# 網頁設計概念：GUI算出的數據 -> Matplotlib畫圖 -> 由Flask回傳轉PNG畫面給瀏覽器 -> 每秒刷新網頁圖片 (main_window.data負責存資料)
# 時域圖：直接讀取最新資料
# FFT 圖：用GUI計算好的FFT

# ================== 預設參數 ==================
DEFAULT_FS = 200.0          # 預設取樣頻率
DEFAULT_N = 11              # 預設 FIR 長度
DEFAULT_T_WINDOW = 5        # 預設顯示秒數
DEFAULT_PORT = "COM3"       # COM 埠

# ================== 資料緩衝區 ==================
class PlotData:
    def __init__(self, max_entries=1000):
        self.x = deque(maxlen=max_entries)
        self.y = deque(maxlen=max_entries)

    def add(self, t, v):
        self.x.append(t)
        self.y.append(v)

    def arrays(self):
        return np.asarray(self.x), np.asarray(self.y)

# ================== 畫圖 ==================
# 第一頁：時域 Raw / Filtered
class TimeDomainWidget(QWidget):
    def __init__(self, parent=None):
        # 初始化QWidget
        super().__init__(parent)

        layout = QVBoxLayout(self)

        # PyQt顯示視窗 + 工具
        self.fig = Figure(figsize=(5, 4))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        # 把畫布與工具列加入layout
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        # 建兩個子圖共用 X 軸
        self.ax_filt = self.fig.add_subplot(2, 1, 1)
        self.ax_raw = self.fig.add_subplot(2, 1, 2, sharex=self.ax_filt)

        self.ax_filt.set_title("Filtered pulse")
        self.ax_raw.set_title("Raw signal")

        self.ax_filt.set_ylim(-1000, 1000)
        self.ax_raw.set_ylim(-1000, 1000)

        (self.line_filt,) = self.ax_filt.plot([], [], "b-", label="Filtered")
        (self.line_raw,) = self.ax_raw.plot([], [], "k-", label="Raw")

        self.ax_filt.legend(loc="upper right")
        self.ax_raw.legend(loc="upper right")

        self.fig.tight_layout()
        
    # X軸實時更新
    def update(self, t, raw, filt,
               show_raw=True, show_filt=True,
               window_sec=5.0):
        if len(t) == 0:
            return

        # 只顯示最後 window_sec 秒
        t_last = t[-1]
        t_start = max(t[0], t_last - window_sec)

        self.ax_filt.set_xlim(t_start, t_last)
        self.ax_raw.set_xlim(t_start, t_last)

        # Raw去DC
        raw_center = raw - raw.mean()

        self.line_filt.set_data(t, filt * 250.0)
        self.line_raw.set_data(t, raw_center * 250.0)

        # 左邊 checkbox 控制顯示/隱藏
        self.line_filt.set_visible(show_filt)
        self.line_raw.set_visible(show_raw)

        self.canvas.draw_idle()


# 第二頁：FFT、 頻率響應(Magnitude、 Phase)
class FreqDomainWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)

        self.fig = Figure(figsize=(5, 5))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        gs = self.fig.add_gridspec(3, 1, height_ratios=[2, 2, 2])
        self.ax_fft = self.fig.add_subplot(gs[0])
        self.ax_mag = self.fig.add_subplot(gs[1])
        self.ax_phase = self.fig.add_subplot(gs[2])

        self.ax_fft.set_title("FFT")
        self.ax_mag.set_title("FIR magnitude")
        self.ax_phase.set_title("FIR phase")

        self.fig.tight_layout()

    def update(self, filt_signal, h_lp, fs):
        global main_window          
        if len(filt_signal) == 0:
            return

        ts = 1.0 / fs

        # ---- FIR 頻率響應 ----
        omega = np.linspace(-np.pi, np.pi, 512)
        H = np.zeros_like(omega, dtype=complex)
        for i, h in enumerate(h_lp):
            H += h * np.exp(-1j * i * omega)

        mag = np.abs(H)
        phase = np.angle(H)

        self.ax_mag.cla()
        self.ax_phase.cla()
        self.ax_mag.set_title("FIR magnitude")
        self.ax_phase.set_title("FIR phase")
        self.ax_mag.plot(omega, mag)
        self.ax_phase.plot(omega, phase)

        # ---- FFT ----
        N_FFT = 2560
        ys_fft = np.fft.fft(filt_signal, N_FFT)
        ys_mag = np.abs(ys_fft) / N_FFT
        freq = np.fft.fftfreq(N_FFT, ts)

        mask = (freq >= 0) & (freq <= 5)   # 只看0~5Hz
        f_pos = freq[mask]
        m_pos = ys_mag[mask]

        peak_idx = np.argmax(m_pos)
        peak_f = f_pos[peak_idx]
        peak_m = m_pos[peak_idx]
        
        # 把 FFT 結果存回主視窗，給Web共用
        if main_window is not None:
            main_window.fft_freq = f_pos
            main_window.fft_mag  = m_pos
            main_window.fft_bpm  = peak_f * 60.0
        
        self.ax_fft.cla()
        self.ax_fft.set_title("FFT")
        self.ax_fft.stem(f_pos, m_pos, linefmt="r-") 
        self.ax_fft.set_xlim(0, 5)
        self.ax_fft.set_ylim(0, max(m_pos) + 0.5)
        self.ax_fft.plot(peak_f, peak_m, "ro")       # peak
        self.ax_fft.text(
            peak_f,
            peak_m,
            f"{peak_f:.2f} Hz ({peak_f*60:.1f} bpm)",
        )

        self.canvas.draw_idle()


# 第三頁：零點
class ZPlaneWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        self.fig = Figure(figsize=(5, 5))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        self.ax = self.fig.add_subplot(1,1,1)
        self.ax.set_title("Zeros on unit circle")
        self.fig.tight_layout()

    def update(self, h_lp):
        if len(h_lp) == 0:
            return

        self.ax.cla()
        self.ax.set_title("Zeros on unit circle")

        # 單位圓
        theta = np.linspace(0, 2 * np.pi, 512)
        circle = np.exp(1j * theta)
        self.ax.plot(np.real(circle), np.imag(circle), "k--")

        # 零點
        zeros = np.roots(h_lp)
        self.ax.plot(np.real(zeros), np.imag(zeros), "bo")

        self.ax.axhline(0, color="gray", linewidth=0.5)
        self.ax.axvline(0, color="gray", linewidth=0.5)

        self.ax.set_xlim(-1.5, 1.5)
        self.ax.set_ylim(-1.5, 1.5)
        self.ax.set_aspect("equal", "box")
        self.ax.grid(True)

        self.canvas.draw_idle()


# ================== 主視窗 ==================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pulse monitor GUI")

        # 狀態：資料、濾波器、取樣設定
        self.data = PlotData(1000)
        self.start_time = None
        self.fs = DEFAULT_FS
        self.N = DEFAULT_N
        self.h_lp = np.ones(self.N) / self.N
        
        #self.ser = None   
        self.fft_freq = None      # GUI目前 FFT 的頻率
        self.fft_mag = None       # GUI目前 FFT 的幅度
        self.fft_bpm = None       # GUI最近一次算出的bpm

        # ---- 中央 Widget：左控制 + 右分頁 ----
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)

        # ========== 左側控制面板 ==========
        ctrl_box = QGroupBox("控制面板")
        ctrl_layout = QVBoxLayout(ctrl_box)

        # --- 取樣設定 ---
        group_sample = QGroupBox("取樣設定")
        sample_layout = QVBoxLayout(group_sample)

        self.spin_fs = QSpinBox()               # 加入介面
        self.spin_fs.setRange(50, 1000)
        self.spin_fs.setValue(int(DEFAULT_FS))

        self.spin_N = QSpinBox()
        self.spin_N.setRange(1, 200)
        self.spin_N.setValue(DEFAULT_N)

        sample_layout.addWidget(QLabel("取樣頻率 (Hz)"))
        sample_layout.addWidget(self.spin_fs)
        sample_layout.addWidget(QLabel("FIR 長度 N"))
        sample_layout.addWidget(self.spin_N)

        # --- 顯示設定 ---
        group_display = QGroupBox("顯示設定")
        display_layout = QVBoxLayout(group_display)

        self.chk_raw = QCheckBox("顯示 Raw")
        self.chk_raw.setChecked(True)           #預設：顯示

        self.chk_filt = QCheckBox("顯示 Filtered")
        self.chk_filt.setChecked(True)

        self.spin_twindow = QSpinBox()
        self.spin_twindow.setRange(1, 30)
        self.spin_twindow.setValue(DEFAULT_T_WINDOW)

        display_layout.addWidget(self.chk_raw)
        display_layout.addWidget(self.chk_filt)
        display_layout.addWidget(QLabel("顯示秒數"))
        display_layout.addWidget(self.spin_twindow)

        # --- 串列埠 ---
        group_port = QGroupBox("串列埠")
        port_layout = QVBoxLayout(group_port)

        self.combo_port = QComboBox()
        self.combo_port.addItems(["COM1", "COM2", "COM3", "COM4"])
        self.combo_port.setCurrentText(DEFAULT_PORT)

        port_layout.addWidget(QLabel("Port"))
        port_layout.addWidget(self.combo_port)

        # --- 開始 / 停止 按鈕 ---
        self.btn_start = QPushButton("開始")
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)

        # 把三個group box + 按鈕丟進ctrl_layout
        ctrl_layout.addWidget(group_sample)
        ctrl_layout.addWidget(group_display)
        ctrl_layout.addWidget(group_port)
        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_stop)
        ctrl_layout.addStretch(1)
        
        main_layout.addWidget(ctrl_box, 0)  # 左邊小

        # ========== 右側分頁 ==========
        self.tabs = QTabWidget()
        self.time_tab = TimeDomainWidget()
        self.freq_tab = FreqDomainWidget()
        self.z_tab = ZPlaneWidget()

        self.tabs.addTab(self.time_tab, "時間訊號")
        self.tabs.addTab(self.freq_tab, "頻率分析")
        self.tabs.addTab(self.z_tab, "Z-plane")

        main_layout.addWidget(self.tabs, 1)  # 右邊大

        # ---- Timer：負責定期讀資料 + 更新畫面 ----
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_all)

        # ---- 按鈕 ----
        self.btn_start.clicked.connect(self.start_acquire)
        self.btn_stop.clicked.connect(self.stop_acquire)

    # ---------- 開始量測 ----------
    def start_acquire(self):
        # 讀取左側設定
        self.fs = float(self.spin_fs.value())
        self.N = int(self.spin_N.value())
        self.h_lp = np.ones(self.N) / self.N  # moving average
        port = self.combo_port.currentText()

        # 開啟串列埠
        try:
            if self.ser is not None and self.ser.is_open:
                self.ser.close()
            self.ser = serial.Serial(port, 115200, timeout=0.1)
            self.ser.flush()
        except Exception as e:
            print("開啟串列埠失敗:", e)
            return

        self.data = PlotData(1000)
        self.start_time = time.time()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        # 按下開始50ms後運作
        self.timer.start(50)

    # ---------- 停止量測 ----------
    def stop_acquire(self):
        self.timer.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if self.ser is not None and self.ser.is_open:
            self.ser.close()

    # ---------- 讀資料 + 更新分頁 ----------
    def update_all(self):
        if self.ser is None or not self.ser.is_open:
            return

        # 讀 N 筆資料
        for _ in range(self.N):
            try:
                line = self.ser.readline()
                if not line:
                    continue
                value = float(line.decode().strip())
                t = time.time() - self.start_time
                self.data.add(t, value)
            except Exception:
                pass

        t, raw = self.data.arrays()
        if len(t) == 0:
            return

        # FIR 濾波（移動平均）
        raw_center = raw - raw.mean()
        filt = np.convolve(raw_center, self.h_lp, mode="same")

        # ---- 分頁 1：時間訊號 ----
        show_raw = self.chk_raw.isChecked()
        show_filt = self.chk_filt.isChecked()
        window_sec = float(self.spin_twindow.value())

        self.time_tab.update(
            t, raw, filt,
            show_raw=show_raw,
            show_filt=show_filt,
            window_sec=window_sec
        )

        # ---- 分頁 2：只有在被選取時才更新 FFT ----
        if self.tabs.currentWidget() is self.freq_tab:
            self.freq_tab.update(filt, self.h_lp, self.fs)

        # ---- 分頁 3：Z-plane ----
        if self.tabs.currentWidget() is self.z_tab:
            self.z_tab.update(self.h_lp)

# ================== 網頁 ==================
flask_app = Flask(__name__)
main_window = None  # 啟動 GUI 時會把實例放進來


@flask_app.route("/")
def index():
    html = """
    <html>
    <head>
        <title>Pulse monitor - Web</title>
    </head>
    <body>
        <h1>即時脈搏監看</h1>

        <h2>時域（Filtered）</h2>
        <img id="plot" src="/plot.png" style="max-width: 900px;">

        <h2>頻域（FFT）</h2>
        <img id="fftplot" src="/fft.png" style="max-width: 900px;">

        <script>
            // 每 1000 ms 更新一次兩張圖
            setInterval(function () {
                var img1 = document.getElementById('plot');
                img1.src = '/plot.png?t=' + new Date().getTime();

                var img2 = document.getElementById('fftplot');
                img2.src = '/fft.png?t=' + new Date().getTime();
            }, 1000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

# --- 濾波波型顯示 ---
@flask_app.route("/plot.png")       #網頁請求
def plot_png():
    global main_window
    if main_window is None:
        return "GUI 尚未啟動", 503

    # 從GUI的PlotData取得目前資料
    t, raw = main_window.data.arrays()
    if len(t) == 0:
        return "尚無資料", 503

    # 拿掉DC + FIR
    raw_center = raw - raw.mean()
    filt = np.convolve(raw_center, main_window.h_lp, mode="same")

    # 只畫最近顯示的 window 秒數
    window_sec = float(main_window.spin_twindow.value())
    t_last = t[-1]
    t_start = max(t[0], t_last - window_sec)
    mask = (t >= t_start) & (t <= t_last)
    t_plot = t[mask]
    y_plot = filt[mask]

    # 畫圖
    fig = Figure(figsize=(6, 3))
    ax = fig.add_subplot(111)
    ax.set_title("Filtered pulse (web)")
    ax.plot(t_plot, y_plot * 250.0)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    fig.tight_layout()

    canvas = FigureCanvasAgg(fig)
    img = io.BytesIO()
    canvas.print_png(img)
    img.seek(0)

    return Response(img.getvalue(), mimetype="image/png")
    
# --- FFT波型顯示 ---
@flask_app.route("/fft.png")
def fft_png():
    global main_window
    if main_window is None:
        return "GUI 尚未啟動", 503

    # 等GUI至少算過一次FFT
    if main_window.fft_freq is None or main_window.fft_mag is None:
        return "尚未有 FFT 資料", 503

    f_pos = main_window.fft_freq
    m_pos = main_window.fft_mag
    bpm_peak = main_window.fft_bpm if main_window.fft_bpm is not None else 0.0

    # 找主峰
    peak_idx = np.argmax(m_pos)
    peak_f = f_pos[peak_idx]

    fig = Figure(figsize=(6, 3))
    ax = fig.add_subplot(111)

    ax.stem(f_pos, m_pos, linefmt="r-")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude")
    ax.set_title(f"FFT (BPM ≈ {bpm_peak:.1f})")

    # 畫線標出峰值
    ax.axvline(peak_f, linestyle="--")
    ax.grid(True)
    fig.tight_layout()

    canvas = FigureCanvasAgg(fig)
    img = io.BytesIO()
    canvas.print_png(img)
    img.seek(0)

    return Response(img.getvalue(), mimetype="image/png")

# ================== 主程式 ==================
if __name__ == "__main__":

    # 啟動 Flask
    def run_flask():
        # use_reloader=False 避免Flask自己再開一個子行程
        flask_app.run(host="0.0.0.0", port=8000, debug=False, use_reloader=False)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 啟動 PyQt GUI
    qt_app = QApplication(sys.argv)
    w = MainWindow()
    w.resize(1200, 700)
    w.show()

    # 把main_window指到目前GUI物件，讓Flask可以讀到資料
    main_window = w

    sys.exit(qt_app.exec_())

