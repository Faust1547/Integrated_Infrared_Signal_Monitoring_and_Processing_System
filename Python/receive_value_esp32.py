import socket

bind_ip = "0.0.0.0"
bind_port = 9999
# 定義分隔符，與 client.println() 發送的 \r\n 相對應
DELIMITER = b'\r\n' 

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((bind_ip, bind_port))
server.listen(5)
print ("Listening on", bind_ip, ",", bind_port)

while True:
    client, addr = server.accept()
    print ('Connected by', addr)
    
    buffer = b'' # 關鍵：初始化緩衝區
    
    try:
        while True:
            # 接收較大塊的數據，放入緩衝區
            data = client.recv(1024) 
            if not data:
                break # 連線斷開

            buffer += data
            
            # 只要緩衝區中還有分隔符，就一直處理
            while DELIMITER in buffer:
                # 分割出第一條完整訊息 (message) 和剩餘的緩衝區 (buffer)
                message, buffer = buffer.split(DELIMITER, 1)
                
                # --- 處理接收到的完整訊息 ---
                try:
                    # 解碼為字串，去除可能存在的空白
                    # message 是 bytes 類型，例如 b'636'
                    sensor_value_str = message.decode('utf-8').strip() 
                    
                    if sensor_value_str: # 避免處理空字串
                        sensor_value = int(sensor_value_str)
                        print(f"Received Value: {sensor_value}")
                    
                except ValueError as e:
                    # 處理非數字的錯誤數據
                    print(f"Warning: Could not convert to int: {message} ({e})")
                
    except ConnectionResetError:
        print(f"Connection from {addr} reset.")
    finally:
        print(f"Connection from {addr} closed.")
        client.close()