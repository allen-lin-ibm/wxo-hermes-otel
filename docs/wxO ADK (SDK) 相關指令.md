## wxO ADK 官方文件 
https://developer.watson-orchestrate.ibm.com

## 安裝 wxO ADK (SDK)
1. `uv add ibm-watsonx-orchestrate`
2. `source ./.venv/bin/activate`
3. `orchestrate env add -n <environment-name> -u <service-instance-url> --type ibm_iam --activate` Ex: `orchestrate env add -n "itz-saas-331-wxo" -u "https://api.jp-tok.watson-orchestrate.cloud.ibm.com/instances/7763d582-bcc4-42b1-8566-1d0a4dbb4107" --type ibm_iam --activate`

## 建立 / 匯出 knowledge base 設定檔
```bash
# 建立 knowledge base
orchestrate knowledge-bases import -f "Allen's 專題競賽投稿文件_import.yaml"

# 匯出 knowledge base 設定檔
orchestrate knowledge-bases export -n Allen_s__5022jR -o "Allen_s__5022jR_export.yaml"
```