import sys
import time
import socket
import threading
import queue
from collections import deque

import matplotlib.pyplot as plt
import numpy as np

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QSpinBox, QGroupBox,
    QCheckBox
)

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvasAgg
from flask import Flask, render_template_string, Response
import io
import base64


# ================== 網路接收與佇列配置 ==================
bind_ip = "0.0.0.0"
bind_port = 9999
DELIMITER = b'\r\n'
TCP_DATA_QUEUE = queue.Queue(maxsize=4000) # 資料佇列，容量可依需求調整


# --- TCP 伺服器/接收執行緒 ---
class TCPReceiverThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.running = True
        self.server_socket = None
        self.client_socket = None

    def run(self):
        # 初始化 Server Socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((bind_ip, bind_port))
        # 設置 timeout 以便檢查 self.running 狀態
        self.server_socket.settimeout(0.5) 
        self.server_socket.listen(1)
        print(f"TCP Receiver: Listening on {bind_ip}:{bind_port}")

        while self.running:
            try:
                # 阻塞等待連線 (會被 timeout 打斷)
                self.client_socket, addr = self.server_socket.accept()
                print(f'TCP Receiver: Connected by {addr}')
                self.receive_data(self.client_socket, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                     print(f"TCP Server Error: {e}")
                break
    
    def receive_data(self, client, addr):
        buffer = b''
        try:
            while self.running:
                # 接收較大塊的數據
                data = client.recv(1024) 
                if not data:
                    break 

                buffer += data
                
                # 分割訊息並放入佇列
                while DELIMITER in buffer:
                    message, buffer = buffer.split(DELIMITER, 1)
                    
                    try:
                        sensor_value_str = message.decode('utf-8').strip() 
                        if sensor_value_str:
                            # 解析為浮點數或整數
                            sensor_value = float(sensor_value_str) 
                            TCP_DATA_QUEUE.put_nowait(sensor_value - 100)
                    except ValueError:
                        print(f"Warning: Data format error - {message}")

        except ConnectionResetError:
            print(f"Connection from {addr} reset.")
        except Exception as e:
            if self.running:
                print(f"Data Receiver Error: {e}")
        finally:
            print(f"Connection from {addr} closed.")
            client.close()

    def stop(self):
        self.running = False
        # 關閉 Socket 以解除阻塞
        if self.server_socket:
            try:
                # 創建一個假的連線來解除 server.accept() 的阻塞
                temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_socket.connect(('127.0.0.1', bind_port))
                temp_socket_close()
            except:
                pass 
            self.server_socket.close()

# ================== 預設參數 ==================
DEFAULT_FS = 200.0          # 預設取樣頻率
DEFAULT_N = 11              # 預設 FIR 長度
DEFAULT_T_WINDOW = 5        # 預設顯示秒數
# ================== 資料緩衝區 ==================
class PlotData:
    def __init__(self, max_entries=2000): # 增加最大容量
        self.x = deque(maxlen=max_entries)
        self.y = deque(maxlen=max_entries)

    def add(self, t, v):
        self.x.append(t)
        self.y.append(v)

    def arrays(self):
        return np.asarray(self.x), np.asarray(self.y)

# ================== 畫圖 (時域) ==================
class TimeDomainWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        self.fig = Figure(figsize=(5, 4))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

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
        
    def update(self, t, raw, filt,
               show_raw=True, show_filt=True,
               window_sec=5.0):
        if len(t) == 0:
            return

        t_last = t[-1]
        t_start = max(t[0], t_last - window_sec)

        self.ax_filt.set_xlim(t_start, t_last)
        self.ax_raw.set_xlim(t_start, t_last)

        raw_center = raw - raw.mean()

        self.line_filt.set_data(t, filt * 250.0)
        self.line_raw.set_data(t, raw_center * 250.0)

        self.line_filt.set_visible(show_filt)
        self.line_raw.set_visible(show_raw)

        self.canvas.draw_idle()


# ================== 畫圖 (頻域/Z平面) (程式碼未更動) ==================
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
        if len(filt_signal) == 0: return
        ts = 1.0 / fs
        # ---- FIR 頻率響應 ----
        omega = np.linspace(-np.pi, np.pi, 512)
        H = np.zeros_like(omega, dtype=complex)
        for i, h in enumerate(h_lp): H += h * np.exp(-1j * i * omega)
        mag = np.abs(H)
        phase = np.angle(H)
        self.ax_mag.cla(); self.ax_phase.cla()
        self.ax_mag.set_title("FIR magnitude"); self.ax_phase.set_title("FIR phase")
        self.ax_mag.plot(omega, mag); self.ax_phase.plot(omega, phase)
        # ---- FFT ----
        N_FFT = 2560
        ys_fft = np.fft.fft(filt_signal, N_FFT)
        ys_mag = np.abs(ys_fft) / N_FFT
        freq = np.fft.fftfreq(N_FFT, ts)
        mask = (freq >= 0) & (freq <= 5)
        f_pos = freq[mask]
        m_pos = ys_mag[mask]
        peak_idx = np.argmax(m_pos)
        peak_f = f_pos[peak_idx]; peak_m = m_pos[peak_idx]
        self.ax_fft.cla(); self.ax_fft.set_title("FFT")
        self.ax_fft.stem(f_pos, m_pos, linefmt="r-")
        self.ax_fft.set_xlim(0, 5); self.ax_fft.set_ylim(0, max(m_pos) + 0.5)
        self.ax_fft.plot(peak_f, peak_m, "ro")
        self.ax_fft.text(peak_f, peak_m, f"{peak_f:.2f} Hz ({peak_f*60:.1f} bpm)")
        self.canvas.draw_idle()

class ZPlaneWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.fig = Figure(figsize=(5, 5))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Zeros on unit circle")
        self.fig.tight_layout()

    def update(self, h_lp):
        if len(h_lp) == 0: return
        self.ax.cla(); self.ax.set_title("Zeros on unit circle")
        # 單位圓
        theta = np.linspace(0, 2 * np.pi, 512)
        circle = np.exp(1j * theta)
        self.ax.plot(np.real(circle), np.imag(circle), "k--")
        # 零點
        zeros = np.roots(h_lp)
        self.ax.plot(np.real(zeros), np.imag(zeros), "bo")
        self.ax.axhline(0, color="gray", linewidth=0.5)
        self.ax.axvline(0, color="gray", linewidth=0.5)
        self.ax.set_xlim(-1.5, 1.5); self.ax.set_ylim(-1.5, 1.5)
        self.ax.set_aspect("equal", "box"); self.ax.grid(True)
        self.canvas.draw_idle()


# ================== 主視窗 (整合網路邏輯) ==================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pulse monitor GUI (TCP)")

        # 狀態：資料、濾波器、取樣設定
        self.data = PlotData(2000)
        self.start_time = None
        self.fs = DEFAULT_FS
        self.N = DEFAULT_N
        self.h_lp = np.ones(self.N) / self.N
        
        # 移除 self.ser，新增 TCP 執行緒物件
        self.tcp_thread = None 

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

        self.spin_fs = QSpinBox(); self.spin_fs.setRange(50, 1000); self.spin_fs.setValue(int(DEFAULT_FS))
        self.spin_N = QSpinBox(); self.spin_N.setRange(1, 200); self.spin_N.setValue(DEFAULT_N)

        sample_layout.addWidget(QLabel("取樣頻率 (Hz)"))
        sample_layout.addWidget(self.spin_fs)
        sample_layout.addWidget(QLabel("FIR 長度 N"))
        sample_layout.addWidget(self.spin_N)

        # --- 顯示設定 ---
        group_display = QGroupBox("顯示設定")
        display_layout = QVBoxLayout(group_display)

        self.chk_raw = QCheckBox("顯示 Raw"); self.chk_raw.setChecked(True)
        self.chk_filt = QCheckBox("顯示 Filtered"); self.chk_filt.setChecked(True)
        self.spin_twindow = QSpinBox(); self.spin_twindow.setRange(1, 30); self.spin_twindow.setValue(DEFAULT_T_WINDOW)

        display_layout.addWidget(self.chk_raw)
        display_layout.addWidget(self.chk_filt)
        display_layout.addWidget(QLabel("顯示秒數"))
        display_layout.addWidget(self.spin_twindow)

        # --- 網路狀態顯示 ---
        group_network = QGroupBox("網路狀態 (Port: 9999)")
        network_layout = QVBoxLayout(group_network)
        self.lbl_status = QLabel("狀態: 未啟動")
        self.lbl_queue = QLabel("佇列長度: 0")
        network_layout.addWidget(self.lbl_status)
        network_layout.addWidget(self.lbl_queue)
        
        # --- 開始 / 停止 按鈕 ---
        self.btn_start = QPushButton("啟動網路接收")
        self.btn_stop = QPushButton("停止接收")
        self.btn_stop.setEnabled(False)

        # 把三個group box + 按鈕丟進ctrl_layout
        ctrl_layout.addWidget(group_sample)
        ctrl_layout.addWidget(group_display)
        ctrl_layout.addWidget(group_network) # 新增網路狀態
        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_stop)
        ctrl_layout.addStretch(1)
        
        main_layout.addWidget(ctrl_box, 0)

        # ========== 右側分頁 (不變) ==========
        self.tabs = QTabWidget()
        self.time_tab = TimeDomainWidget()
        self.freq_tab = FreqDomainWidget()
        self.z_tab = ZPlaneWidget()
        self.tabs.addTab(self.time_tab, "時間訊號")
        self.tabs.addTab(self.freq_tab, "頻率分析")
        self.tabs.addTab(self.z_tab, "Z-plane")
        main_layout.addWidget(self.tabs, 1)

        # ---- Timer：負責定期讀資料 + 更新畫面 (運行在主執行緒) ----
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_all)

        # ---- 按鈕事件 ----
        self.btn_start.clicked.connect(self.start_acquire)
        self.btn_stop.clicked.connect(self.stop_acquire)

    # ---------- 開始量測 (啟動 TCP 執行緒) ----------
    def start_acquire(self):
        # 讀取左側設定
        self.fs = float(self.spin_fs.value())
        self.N = int(self.spin_N.value())
        self.h_lp = np.ones(self.N) / self.N
        
        # 啟動 TCP 接收執行緒
        if self.tcp_thread is None or not self.tcp_thread.is_alive():
            self.tcp_thread = TCPReceiverThread()
            self.tcp_thread.start()
            self.lbl_status.setText("狀態: 監聽中...")

        # 清空資料緩衝區並重設時間
        self.data = PlotData(2000)
        self.start_time = time.time()
        
        # 更新 GUI 狀態
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.timer.start(50) # Timer (50ms)

    # ---------- 停止量測 (停止 TCP 執行緒) ----------
    def stop_acquire(self):
        self.timer.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        
        # 停止 TCP 接收執行緒
        if self.tcp_thread is not None and self.tcp_thread.is_alive():
            self.tcp_thread.stop()
            self.tcp_thread.join() 
            self.tcp_thread = None
        
        self.lbl_status.setText("狀態: 已停止")

    # ---------- 讀資料 + 更新分頁 (從佇列讀取) ----------
    def update_all(self):
        self.lbl_queue.setText(f"佇列長度: {TCP_DATA_QUEUE.qsize()}")
        
        # 檢查 TCP 執行緒狀態
        if self.tcp_thread is None or not self.tcp_thread.is_alive():
             self.lbl_status.setText("狀態: 錯誤/已斷開")
             return

        # 從佇列中一次讀取所有累積的資料，加入 PlotData
        read_count = 0
        while not TCP_DATA_QUEUE.empty():
            try:
                # 從佇列中取出資料 (非阻塞)
                value = TCP_DATA_QUEUE.get_nowait()
                t = time.time() - self.start_time
                self.data.add(t, value)
                read_count += 1
            except queue.Empty:
                break 

        # 如果沒有新資料，則直接返回，不進行耗時的繪圖更新
        if read_count == 0:
            return

        # --- 訊號處理與繪圖 ---
        t, raw = self.data.arrays()
        if len(t) == 0:
            return

        # FIR 濾波（移動平均）
        raw_center = raw - raw.mean()
        filt = np.convolve(raw_center, self.h_lp, mode="same")

        # ---- 更新分頁 1：時間訊號 ----
        show_raw = self.chk_raw.isChecked()
        show_filt = self.chk_filt.isChecked()
        window_sec = float(self.spin_twindow.value())

        self.time_tab.update(
            t, raw, filt,
            show_raw=show_raw,
            show_filt=show_filt,
            window_sec=window_sec
        )

        # ---- 分頁 2/3：只有在被選取時才更新 ----
        if self.tabs.currentWidget() is self.freq_tab:
            self.freq_tab.update(filt, self.h_lp, self.fs)

        if self.tabs.currentWidget() is self.z_tab:
            self.z_tab.update(self.h_lp)


# ================== 網頁用 Flask (未更動) ==================
flask_app = Flask(__name__)
main_window = None


@flask_app.route("/")
def index():
    html = """
    <html>
    <head>
        <title>Pulse monitor - Web</title>
    </head>
    <body>
        <h1>即時脈搏圖（Filtered）</h1>
        <img id="plot" src="/plot.png" style="max-width: 900px;">
        <script>
            setInterval(function () {
                var img = document.getElementById('plot');
                img.src = '/plot.png?t=' + new Date().getTime();
            }, 1000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@flask_app.route("/plot.png")
def plot_png():
    global main_window
    if main_window is None or main_window.start_time is None:
        return "GUI 尚未啟動", 503

    t, raw = main_window.data.arrays()
    if len(t) == 0:
        return "尚無資料", 503

    # 跟 GUI 一樣做簡單處理（去 DC + FIR）
    raw_center = raw - raw.mean()
    filt = np.convolve(raw_center, main_window.h_lp, mode="same")

    # 顯示window秒數
    window_sec = float(main_window.spin_twindow.value())
    t_last = t[-1]
    t_start = max(t[0], t_last - window_sec)
    mask = (t >= t_start) & (t <= t_last)
    t_plot = t[mask]
    y_plot = filt[mask]

    fig = Figure(figsize=(6, 3))
    ax = fig.add_subplot(1,1,1)
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
    
# ================== 主程式 ==================
if __name__ == "__main__":
    # 啟動網頁
    def run_flask():
        flask_app.run(host="0.0.0.0", port=8000, debug=False, use_reloader=False)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # GUI介面
    app = QApplication(sys.argv)
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    
    main_window = w
    
    try:
        sys.exit(app.exec_())
    finally:
        # 確保在程式結束時停止 TCP 執行緒
        if w.tcp_thread is not None and w.tcp_thread.is_alive():
             w.tcp_thread.stop()
             w.tcp_thread.join()