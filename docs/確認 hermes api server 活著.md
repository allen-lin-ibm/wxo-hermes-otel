## 確認 Hermes 是否正在運作
### 查看 Gateway 狀態
```bash
hermes gateway status
```

查看 Gateway 是否正在執行，以及 PID 等資訊。

### 確認 Port 8642 是否正在監聽
```bash
lsof -nP -iTCP:8642 -sTCP:LISTEN
```

如果有看到類似：
```bash
COMMAND   PID   USER   FD   TYPE ... TCP 127.0.0.1:8642 (LISTEN)
```
就代表有程序正在監聽 8642。

### 實際呼叫 API
```bash
curl -i http://127.0.0.1:8642/v1/models \
  -H "Authorization: Bearer YOUR_API_SERVER_KEY"
```

預期結果：
HTTP/1.1 200 OK

並且回傳 hermes-agent。

### 查看模型
```bash
curl -s http://127.0.0.1:8642/v1/models \
  -H "Authorization: Bearer YOUR_API_SERVER_KEY" | python3 -m json.tool
```

### 測試對話
```bash
curl -s http://127.0.0.1:8642/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_SERVER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-agent",
    "messages": [
      {"role": "user", "content": "Hello Hermes"}
    ],
    "stream": false
  }' | python3 -m json.tool
```


## Hermes Gateway 常用指令
指令	用途
hermes gateway status	查看 Gateway 狀態
hermes gateway start	啟動背景服務
hermes gateway stop	停止 Gateway
hermes gateway restart	重新啟動 Gateway
hermes gateway	在前景啟動 Gateway
hermes gateway list	查看各 Profile 的 Gateway 狀態
