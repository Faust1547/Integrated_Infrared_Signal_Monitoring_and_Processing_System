# Python & Arduino

## Overview
本專案結合 Arduino 與 Python 建立即時紅外線訊號監測系統。Arduino 負責擷取感測器的類比訊號，並透過 Serial 傳送至 Python 端，進行 FIR 濾波、FFT 頻率分析及濾波器特性計算。系統使用 PyQt5 建立圖形化操作介面，並透過 Flask 提供網頁監控功能，定期更新訊號波形與頻譜。

## System Functions
|Function|Description|
|---|---|
|Serial Communication|透過 COM Port 接收 Arduino 傳送的感測器資料|
|FIR Filtering	|使用可調整長度的移動平均 FIR Filter，平滑訊號並抑制雜訊|
|FFT Analysis|	將濾波後的訊號轉換至頻域，擷取主要頻率並換算 BPM|
|Frequency Response|	計算 FIR Filter 的 Magnitude 與 Phase Response|
|Z-Plane Analysis|	計算並顯示 FIR Filter 的零點分布|
|PyQt5 GUI|	即時顯示訊號、頻譜及濾波器特性，提供取樣與顯示參數調整|
|Web Monitoring	|透過 Flask 提供網頁，定期更新濾波後訊號及 FFT 圖表|

 ## Execution
Python 端需要用到以下函式庫：
* numpy
* matplotlib
* pyserial
* PyQt5
* flask

以下為程式執行步驟：
1. 將 analog_read.ino 上傳至 Arduino UNO，確認其 Serial Baud Rate 與 Python 程式設置一致。
2. 將 Arduino 連接至電腦，確認實際使用的 COM Port。
3. 透過 cmd 執行 `python pulse_plot.py`，並在 PyQt5 GUI 中選擇 COM Port，設定取樣頻率與 FIR 長度，再按下開始。
4. 如需網頁監控，在執行程式的電腦上開啟 `http://localhost:8000`。

 ## File Description
|File|Description|
|---|---|
|analog_read.ino|Arduino 端程式，讀取感測器類比訊號，並透過 Serial 傳送至電腦|
|pulse_plot.py	|Python 主程式，負責接收訊號、FIR 濾波、FFT 分析、GUI 顯示及網頁監控|
