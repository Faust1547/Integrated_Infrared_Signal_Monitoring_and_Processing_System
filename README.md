# Integrated Infrared Signal Monitoring and Processing System

## Overview
本專案以紅外光感測器與 Arduino UNO 建立即時脈搏監測系統，並整合訊號處理與圖形化介面。量測訊號先經由 FIR Filter 進行平滑與雜訊抑制，再透過 FFT 分析主要頻率成分並換算為每分鐘脈搏次數（bpm）。此外，系統以 PyQt 建立即時操作介面，可同步顯示時域波形、FFT 頻譜、FIR frequency response 與 Z-plane；並透過 TCP 接收感測資料，再由 Flask Web Interface 提供即時遠端監看功能。

## Hardware
由 Arduino UNO 與紅外光感測器組成。

 <img width="456" height="407" alt="image" src="https://github.com/user-attachments/assets/f3d075ef-9299-4766-9463-d11a96cee95d" />

## Results
1. 操作畫面說明
2. Demo 影片

_Portfolio version prepared by TSAI An-Hao, September 29, 2026._
