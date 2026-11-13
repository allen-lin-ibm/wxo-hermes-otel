# Hermes Agent trace → wxO（Option 1：Generic OTel Export）計畫

## Top-Level Overview

**目標**：把本機 Hermes Agent 的執行 trace（session / LLM / API / tool / sub-agent）送進 wxO 的 Agent Analytics。

**做法**：依 [`docs/WXO_External_Agent_Observability_Guide.pdf`](docs/WXO_External_Agent_Observability_Guide.pdf) 的 Option 1（標準 OTel、OTLP/HTTP、不使用 WXO 專屬 SDK），在 Hermes 端使用社群 plugin `hermes_otel`（v1.18.2，需 Hermes >= 0.21）產生 span。

**架構決策（已與使用者確認）**：Hermes 不直送 wxO，改經本機 OTel Collector 中介，原因：
1. PDF 的認證是用 `API_KEY` 向 `TOKEN_URL` 換 Bearer token，token 會過期，而 Hermes gateway 長時間執行；plugin 文件只看到靜態 `api_key` / `${VAR}`，沒看到動態換 token 的機制。
2. wxO 需要 `agent.id`（span attribute）、`tenant.id` 與 `deployment.environment`（resource attribute），plugin 預設不帶，由 Collector 統一補上。

**資料流**：
Hermes + hermes_otel → (OTLP/HTTP，無認證，localhost:4318) → Podman 內的 OTel Collector（補 attribute、帶 Bearer token）→ wxO `.../v1/orchestrate/inject/traces`。
另有一支 token 更新腳本，定時向 `TOKEN_URL` 換 token 並寫入檔案，供 Collector 讀取。

**Token 熱更新機制**：
- 使用 Collector contrib 的 `bearertokenauth` extension 的 `filename` 選項（監看檔案，變動時自動換 token）。**此行為為依記憶判斷，需在 PoC 驗證。**
- Podman 掛載「目錄」，不掛單一檔案（避免 rename 造成 inode 不一致）。
- 備案：若容器內抓不到檔案變動，更新腳本改為更新 token 後 `podman restart` Collector。注意 `podman restart` 不會重讀 `env_file`，所以 token 不放 `env_file`。
- `env_file: .env` 只放不常變的值：`AGENT_ID`、`TENANT_ID`、`ENVIRONMENT_NAME`、`OTEL_EXPORT_URL`。

**已確認的決定**：
- `content_capture: full`（完整 prompt / response 送進 wxO，使用者已接受）。
- Agent ID 已由使用者在 wxO UI 手動建立，並已寫入專案根目錄 [`.env`](.env)；`TENANT_ID` 也在同一份 `.env`。
- **所有設定值一律從 `.env` 讀取，不寫死在 Collector config、compose 檔或腳本中。** `.env` 內容因被 `.gitignore` 排除，規劃時未讀取，變數名稱以 PDF 3.2 為準（`TENANT_ID`、`AGENT_ID`、`ENVIRONMENT_NAME`、`OTEL_EXPORT_URL`、`API_KEY`、`TOKEN_URL`）。使用者已將 `.env` 中的 Tenant ID 變數更正為 `TENANT_ID`，與 PDF 一致。送到 wxO 的 resource attribute 名稱為 `tenant.id`，由 Collector 將 `${env:TENANT_ID}` 對應過去。

**非目標**：
- 不使用 Option 2（WXO Observability SDK）。
- 不傳 metrics / logs 到 wxO（Collector 只配置 traces pipeline）。
- 不修改 hermes_otel plugin 原始碼。

## 已知事實（來源）

- `~/.hermes/plugins/` 目前為空，hermes_otel 尚未安裝。
- **目前 Hermes 與 wxO 之間使用的是 OpenAI-compatible Chat Completions API**（`/v1/chat/completions`，Hermes `api_server` 平台，port 8642，經 Cloudflare tunnel 對外；網址記在 [`docs/chat completion url.md`](docs/chat%20completion%20url.md)）。證據：trace 的 `llm.api_mode` 為 `chat_completions`、`session.id` 為 `api-<hash>`、`hermes.platform` 為 `api_server`。
- `~/.hermes/config.yaml` 另有 `a2a.trusted_peers: [wxo]`，Hermes 也開著 A2A（port 9900，[`docs/啟動 Cloudflare quick tunnel.md`](docs/啟動 Cloudflare quick tunnel.md) 有記錄啟動 tunnel 的指令），但**目前 wxO 並未使用 A2A 呼叫 Hermes**，A2A 不在這次範圍內。
- 專案資料夾已重整：參考文件集中在 `docs/`，Hermes 相關 txt token 檔已不在工作區根目錄。
- [`.gitignore`](.gitignore) 已排除 `.env`，但尚未排除 token 檔所在目錄。
- Hermes gateway 指令：`hermes gateway status / start / stop / restart`（見 [`docs/確認 hermes api server 活著.md`](docs/確認 hermes api server 活著.md)），安裝或修改 plugin 設定後需 `hermes gateway restart`。
- hermes_otel 設定檔為 `~/.hermes/hermes_otel.yaml`，`backends:` 清單，`type: otlp` 可接任意 OTLP/HTTP endpoint，支援 `${VAR}` 展開；scalar 設定亦可用 `HERMES_OTEL_*` 環境變數。
- hermes_otel 預設 `content_capture: full`（完整 prompt / response 都會送出）。
- 本機有 `~/.hermes/hermes-agent/scripts/observability/otel_capture_collector.py`，可在 :4318 接收並記錄 OTLP payload。
- PDF 未附 `test_otel_export.py`，因此 token 端點的回應格式（欄位名稱、有效期限）尚未確認。
- 專案根目錄尚無 `otel-collector/` 目錄，需新建。

## Sub-Tasks

### 1. 取得 wxO 端所需的值

- **Intent**：備齊 PDF 第 2 節列出的四個值，加上 export URL。
- **Expected Outcomes**：有一份（不入版控的）`.env`，內含 `TENANT_ID`、`AGENT_ID`、`ENVIRONMENT_NAME`、`OTEL_EXPORT_URL`、`API_KEY`、`TOKEN_URL`。
- **Todo List**：
  1. `AGENT_ID` 與 `TENANT_ID` 已寫入 `.env`（使用者已更正 Tenant ID 的變數名稱），不需再取得。
  2. 取得 API key 與對應的 TOKEN_URL。
  3. 組出 `OTEL_EXPORT_URL`（格式見 PDF 3.2：`.../instances/<instance-id>/v1/orchestrate/inject/traces`）。
  4. 補齊 `.env` 尚缺的變數（`ENVIRONMENT_NAME`、`OTEL_EXPORT_URL`、`API_KEY`、`TOKEN_URL`），並在 `.gitignore` 加入 token 檔所在目錄；提供不含機密的 `.env.example`。
- **Relevant Context**：`docs/WXO_External_Agent_Observability_Guide.pdf` 第 2、3.2 節；`.env`、`.gitignore`。
- **Status**：`[x] done`
- **交接資訊（子任務 2 與 3 參考）**：
  - 現行 `.env` 內已有變數：`AGENT_ID`、`TENANT_ID`。
  - 使用者待填入變數：`ENVIRONMENT_NAME`、`OTEL_EXPORT_URL`、`API_KEY`、`TOKEN_URL`。
  - Token 目錄路徑已定為：`otel-collector/token/`，並已加入 [`.gitignore`](.gitignore)。
  - 環境變數範本已建立於 [`.env.example`](.env.example)。

### 2. Token 更新腳本

- **Intent**：自動用 API key 換 Bearer token 並寫入檔案，讓 Collector 不需處理過期。
- **Expected Outcomes**：指定目錄下有 token 檔，會在到期前被更新；寫入為原子操作；失敗時有日誌且保留舊 token。
- **Todo List**：
  1. 先用 curl 手動呼叫 `TOKEN_URL` 確認請求格式與回應欄位、token 有效期。
  2. 寫 Python 腳本（專案已有 uv / `pyproject.toml`），週期短於 token 有效期。
  3. 以暫存檔 + rename 寫入 token 檔（僅 token 字串，無換行問題需確認）。
  4. 以 launchd 或其他方式讓它常駐；確認機制與 Hermes gateway 的啟動方式相容。
- **Relevant Context**：`pyproject.toml`、`.python-version`、PDF 3.3.2（bearer / MCSP_v2 / x-api-key 三種認證，需確認本環境用哪一種）。
- **Status**：`[x] done`
- **交接資訊（子任務 3 參考）**：
  - **Token 檔實際路徑與格式**：[`otel-collector/token/token`](otel-collector/token/token)，內容為純 JWT Bearer Token 字串（長度約 1439 bytes，無結尾換行 `\n` 或 `\r`），檔案權限設為 `0600`。
  - **Token 端點與有效期**：`TOKEN_URL` 實測為 IBM Cloud IAM OAuth (`https://iam.cloud.ibm.com/identity/token`)，使用 `grant_type=urn:ibm:params:oauth:grant-type:apikey`，回應 HTTP 200，欄位包含 `access_token`、`token_type: Bearer`、`expires_in: 3600` 秒（1 小時）。
  - **認證類型實測結論**：確認為 **Bearer 認證**（對應 PDF 3.3.2 中的 Bearer Token 模式），非 MCSP_v2 或 x-api-key。
  - **OTEL_EXPORT_URL 驗證**：已使用該 Bearer Token 對 `OTEL_EXPORT_URL` 發送 OTLP HTTP trace 驗證，返回 HTTP 400（錯誤訊息為 `Missing tenant.id on spans`），證明 Token 認證已成功通過，服務正常接受 trace 請求。
  - **腳本位置與啟動方式**：
    - 單次執行：`uv run python otel-collector/refresh_token.py --once`
    - 常駐執行：`uv run python otel-collector/refresh_token.py`（預設在 Token 到期前剩 20% 時間時自動換新，每約 48 分鐘更新一次；失敗時每 30 秒重試並保留舊 token）。
    - macOS launchd 範本：[`otel-collector/com.wxo.tokenrefresher.plist.template`](otel-collector/com.wxo.tokenrefresher.plist.template)（可依需求替換路徑後部署至 `~/Library/LaunchAgents/`）。
  - **對子任務 3 的 bearertokenauth 設定影響**：
    - Collector 的 extension 請配置 `bearertokenauth` 並將 `filename` 指向掛載的 token 檔（如容器內 `/etc/otelcol/token/token`）。
    - 因 token 為標準 Bearer JWT，exporter `otlphttp` 的 `auth.authenticator` 直接指向此 `bearertokenauth` extension 即可。

### 3. 建立 OTel Collector（Podman）

- **Intent**：提供 Hermes 可無認證送入的 localhost endpoint，並負責補 attribute 與帶 token 轉送 wxO。
- **Expected Outcomes**：Collector 容器啟動後，接收 localhost:4318 的 OTLP/HTTP traces，轉送 wxO 成功（HTTP 2xx）。
- **Todo List**：
  1. [x] 選用 `otel/opentelemetry-collector-contrib` 映像（需 contrib 才有 `bearertokenauth`）。
  2. [x] 撰寫 Collector config：
     - receiver：`otlp`（http，0.0.0.0:4318，並只對 host 的 127.0.0.1 發佈 port）。
     - processor：`resource` 補 `tenant.id`、`deployment.environment`；`attributes` 對每個 span 補 `agent.id`；視需要 `batch`。
     - extension：`bearertokenauth` 使用 `filename` 指向掛載的 token 檔。
     - exporter：`otlphttp`，`traces_endpoint` 使用 `OTEL_EXPORT_URL`，auth 指向 `bearertokenauth`。
     - service：只啟用 traces pipeline。
  3. [x] 撰寫 compose 檔（`podman compose`）：`env_file` 改為 `environment:` 逐一引用，只注入 Collector 需要的四個變數（不注入 API_KEY / TOKEN_URL）、volume 掛 token 目錄與 config。
  4. [x] 驗證 token 檔更新後，Collector 不重啟即使用新 token（已確認：bearertokenauth 每次請求重讀檔案）。
  5. [ ] 設定 `restart` 策略，確保 Mac 重開後自動啟動（需確認 Podman machine 是否隨登入啟動）。
- **Relevant Context**：PDF 3.1 / 3.3.1；`.env`；新增的 Collector config 與 compose 檔位置（建議放在 `otel-collector/` 子目錄）。
- **Status**：`[x] done`
- **交接資訊（子任務 4 參考）**：
  - **映像版本**：`docker.io/otel/opentelemetry-collector-contrib:0.164.0`（2026-11 最新穩定版；`podman-compose` 1.5.0 可用）。
  - **掛載實測結果**：OneDrive 含中文與空格的完整路徑（`~/Library/CloudStorage/OneDrive-IBM/2026 2H/Wiwynn 緯穎/wxO/wxo-enablement/otel-collector/token`）直接掛載至容器 `/etc/otelcol/token` **成功**。bind mount 同步即時（rename 原子寫入後容器立即看到新檔案）。
  - **config 檔位置**：[`otel-collector/config.yaml`](otel-collector/config.yaml)
  - **compose 檔位置**：[`otel-collector/compose.yaml`](otel-collector/compose.yaml)
  - **啟動指令**：
    ```bash
    cd <project-root>
    set -a && source .env && set +a   # 載入 .env 到宿主機 shell
    podman compose -f otel-collector/compose.yaml up -d
    ```
  - **停止指令**：
    ```bash
    podman compose -f otel-collector/compose.yaml down
    ```
  - **wxO 接受的 attribute 層級結論**：
    - 子任務 2 的錯誤 `Missing tenant.id on spans` 確認為 **span 層級**的要求。
    - 目前 config 同時在 resource 層級（`resource` processor）與 span 層級（`attributes` processor）補上 `tenant.id`，以及在 resource 補 `deployment.environment`、span 補 `agent.id`。
    - 測試結果：刻意不在 curl payload 帶 `tenant.id`，Collector 補上後送出，wxO 回應 **HTTP 200** `{"partialSuccess":{}}` → 驗證通過。
  - **熱更新結論**：`bearertokenauth` 的 `filename` 選項在每次發出 HTTP 請求時重新讀取 token 檔（由 `credentialsfile.WithOnChange` 回呼觸發；Collector 日誌可見 `refresh token` 事件）。`refresh_token.py --once` 原子寫入新 token 後，不重啟容器即可使用新 token — 已實測兩次 curl，均回應 HTTP 200。
  - **已知限制**：
    - `compose.yaml` 的變數注入方式（`environment: VAR:` 無值）需在啟動前先執行 `source .env` 載入宿主機 shell，否則容器收不到值，Collector config 會收到空字串。
    - `otlphttp` exporter 名稱在 0.164.0 已標示 deprecated，建議後續改為 `otlp_http`（功能相同）。
    - Podman machine 是否隨 macOS 登入自動啟動、容器 `restart: unless-stopped` 是否跨重開機生效，尚未驗證（子任務 3 待辦 5）。
    - `.env` 第 1–2 行有 python-dotenv 解析警告（格式問題），但 `source .env` 與 `refresh_token.py` 讀取 `.env` 均可正常運作，不影響 Collector 啟動（變數由 shell 注入，不走 python-dotenv）。

### 4. 安裝並設定 hermes_otel（先 PoC，後正式）

- **Intent**：讓 Hermes 產生 span，先確認內容與 attribute，再接到 Collector。
- **Expected Outcomes**：Hermes 回應一次對話後，Collector 收到完整 span 樹（agent → llm → api → tool）。
- **Todo List**：
  1. [x] `hermes plugins install hermes_otel`（catalog name，非 `hermes-otel`），再 `hermes plugins enable hermes_otel`，重啟 gateway。
  2. [x] PoC：直接把 `~/.hermes/hermes_otel.yaml` 的 endpoint 指到正式 Collector（`http://127.0.0.1:4318/v1/traces`），因 Collector 已有 debug exporter 可看 payload；使用者決定跳過 `otel_capture_collector.py` 步驟。
  3. [ ] 切換到正式 Collector（已完成，與 PoC 同步）：`endpoint: http://127.0.0.1:4318/v1/traces`。
  4. [x] 決定 `content_capture: full`（使用者已明確接受）。
  5. [x] 驗證：gateway status 顯示 `[hermes-otel] ✓ OTLP at http://127.0.0.1:4318/v1/traces (traces only)`，Collector debug 日誌收到 spans，wxO 轉送無 error。
- **Relevant Context**：`~/.hermes/config.yaml`、`~/.hermes/plugins/`、`~/.hermes/hermes_otel.yaml`、`~/.hermes/hermes-agent/plugin-catalog/hermes_otel.yaml`。
- **Status**：`[~] PoC 完成`（正式切換與子任務 5 驗證待後續使用者確認）

- **交接資訊（子任務 5 參考）**：

  #### Plugin 實際版本與安裝方式
  - **版本**：`1.18.2`，SHA `d234865b13e997e0b3a50dc18aaad7c7d7b1b1fe`（catalog 固定版本）。
  - **安裝指令**：`hermes plugins install hermes_otel`（用 catalog name，底線；`hermes-otel` 連字號會裝到 repo root 而非 plugin subdir，需先 remove 再重裝）。
  - **啟用指令**：`hermes plugins enable hermes_otel`。
  - **手動安裝套件**：`hermes plugins enable` 有時不會自動安裝 Python 套件；需確認 Hermes 使用的 Python（`/Users/allen/.hermes/tools/python-3.14.9+20261021-darwin-arm64/bin/python3`）能 `import opentelemetry`。若不行，手動執行：
    ```bash
    /Users/allen/.hermes/tools/python-3.14.9+20261021-darwin-arm64/bin/pip install \
      "opentelemetry-api>=1.35,<2" "opentelemetry-sdk>=1.35,<2" \
      "opentelemetry-exporter-otlp-proto-http>=1.35,<2" "PyYAML>=6,<7"
    ```
  - **設定檔位置**：`~/.hermes/hermes_otel.yaml`（不在 plugin 目錄，避免重裝 plugin 覆蓋）。

  #### 設定檔內容（`~/.hermes/hermes_otel.yaml`）
  ```yaml
  project_name: hermes-agent
  content_capture: full
  backends:
    - type: otlp
      endpoint: http://127.0.0.1:4318/v1/traces
      metrics: false
      logs: false
  ```
  - **`type: otlp` 的實際欄位**：`endpoint`（完整 URL，**不**自動補 `/v1/traces`），`metrics`（bool），`logs`（bool）。`type: lgtm` 功能完全相同，差異僅 display name，可互換。

  #### 觀察到的 Span 樹（Trace ID `e8d2e43b80f3e4bae5b57862b26fff2a`）
  對話「請用一句話自我介紹」觸發的 trace（3 ResourceSpans，5 spans，agent 做了 1 次 tool call + 2 次 LLM 呼叫）：
  ```
  agent  [root, AGENT kind]
  ├── llm.llama-3-3-70b-instruct  [turn 1, LLM kind]
  │   └── api.*  [Internal, 2 個 LLM API call spans]
  └── tool.web_search  [pre/post_tool_call hook]
  ```
  **注意**：ResourceSpans 有 3 個，表示 hermes_otel 依 span 類型分批送出（agent/session spans、llm spans、tool spans 各為一批）。

  #### Resource Attribute（hermes_otel 送出）
  | key | value（範例） |
  |---|---|
  | `service.name` | `hermes-agent` |
  | `service.version` | `1.18.2`（plugin 版本） |
  | `service.instance.id` | UUID（每次啟動新值） |
  | `hermes.profile` | `default` |
  | `tenant.id` | *（由 Collector `resource` processor 補上）* |
  | `deployment.environment` | `draft`（由 Collector `resource` processor 補上） |

  #### Span-level Attribute（主要欄位，機密已省略）
  | key | 出現位置 |
  |---|---|
  | `session.id` / `session_id` | agent, llm spans |
  | `gen_ai.conversation.id` | agent, llm spans |
  | `traceloop.span.kind` | 全部（AGENT / LLM / TOOL） |
  | `openinference.span.kind` | 全部（AGENT / LLM / TOOL） |
  | `gen_ai.operation.name` | agent（invoke_agent）、llm（chat） |
  | `gen_ai.request.model` / `gen_ai.response.model` | llm spans |
  | `llm.token_count.prompt` / `.completion` / `.total` | agent, llm spans |
  | `gen_ai.usage.input_tokens` / `output_tokens` | agent, llm spans |
  | `hermes.turn.number` | agent, llm spans |
  | `hermes.platform` | agent span（`api_server`） |
  | `agent.id` | **全部 spans**（由 Collector `attributes` processor 補上） |
  | `tenant.id` | **全部 spans**（由 Collector `attributes` processor 補上） |
  | `input.value` / `output.value` | agent, llm spans（`content_capture: full` 下為完整 prompt/回應） |
  | `gen_ai.input.messages` / `gen_ai.output.messages` | llm spans（JSON 格式完整訊息） |
  | `wandb.is_turn` / `wandb.thread_id` | agent span（內建，不影響 wxO） |
  | `weave.agent.version` | agent span（`1.18.2`） |

  #### langfuse.* / user.* attribute 觀察
  - **沒有** `langfuse.session.id` / `langfuse.user.id`。
  - **有** `session.id`（值同 `gen_ai.conversation.id`，為 Hermes API session id，格式 `api-<hash>`）。
  - 子任務 5 需確認 wxO 是否需要 `langfuse.user.id` 才能在 Conversations 顯示使用者資訊。

  #### 轉送 wxO 結果
  - Collector debug exporter：`10:01:24.369Z`，resource spans=3，spans=5，全部輸出正常。
  - `otlphttp/wxo` exporter：**無任何 error/warn 日誌**，代表轉送成功（HTTP 200/partialSuccess）。
  - 唯一警告：啟動時 `"otlphttp" alias is deprecated; use "otlp_http" instead`（不影響功能，子任務 6 可升級設定）。

  #### 遇到的問題與處理方式
  1. **安裝名稱陷阱**：`hermes plugins install hermes-otel`（連字號）會安裝 repo root 而非 plugin，需改為 `hermes plugins install hermes_otel`（底線，catalog name）。
  2. **OTel 套件未自動安裝**：`hermes plugins enable hermes_otel` 回應「OpenTelemetry packages not available」，需手動 pip install 到 Hermes tools Python。已確認版本：`opentelemetry-api 1.45.2`。
  3. **Gateway restart 前景執行**：`hermes gateway restart` 在前景執行且 SIGTERM 停止 gateway；需接著執行 `hermes gateway start` 讓 gateway 以 detached 模式（launchd）重啟。

  #### 待決事項（供使用者與子任務 5 參考）
  - Collector debug exporter 目前 `verbosity: detailed`，會完整印出 LLM prompt/回應（system prompt 數 KB）。考慮在確認 PoC 後降為 `verbosity: basic`，以減少 Podman logs 量。**不在本子任務自行修改**，待使用者確認。
  - `otlphttp` alias deprecated 警告：後續改為 `otlp_http`（子任務 6）。
  - wxO Analytics 是否實際顯示 trace（子任務 5 驗證）。

### 5. 端對端驗證（wxO Analytics）

- **Intent**：確認 trace 真正出現在 wxO，並比對 PDF 預期的畫面。
- **Expected Outcomes**：Analytics → 該 agent → Overview / Conversations 顯示對話數、token、耗時等；token 過期後仍持續有資料。
- **Todo List**：
  1. [~] 對 Hermes 的 OpenAI-compatible Chat Completions API 對話一次，產生 trace（已完成）。**但那次是在本機直接打 `127.0.0.1:8642`，不是從 wxO 經 Cloudflare tunnel 呼叫。尚未確認：從 wxO UI 對話（wxO 的 external agent 走 chat completions）時，產生的 trace 是否同樣進到 `allen-hermes-test` 的 Analytics，session 是否與 wxO 的對話對應。**
  2. [x] 在 wxO Analytics 查看資料：已出現（見下方驗證結果）。
  3. [~] 檢查 `langfuse.session.id` / `langfuse.user.id`：wxO 沒有它們也能顯示 trace 與對話，但 User 欄位顯示 `Unknown`。是否要補 user id 待使用者決定。
  4. [ ] 等 token 過期後再次對話，確認熱更新有效。token 檔目前由 launchd 服務維護，約每 48 分鐘更新一次；需在至少一次自動更新之後再對話一次來驗證。
- **Relevant Context**：PDF 第 1、3.3、3.4 節；Collector 日誌。
- **Status**：`[~] 部分完成`（trace 已進 wxO；「從 wxO 經 chat completions 呼叫 Hermes」的路徑、token 自動更新後的持續性、User 欄位待處理）

- **驗證結果（使用者在 wxO UI 實際查看，2026-11-02）**：
  - 位置：Analytics → `allen-hermes-test`（Agent ID `9da1a55f-ccd9-405f-b363-79b69d2f4fdf`）→ Conversations。
  - 對話列表出現 `api-74e29270d33adf91`（即 Hermes 的 `session.id`），對話內容「請用一句話自我介紹」與 Hermes 回覆完整顯示。
  - Trace view 的 Trace ID `e8d2e43b80f3e4bae5b57862b26fff2a`，與 Collector 日誌記錄的同一筆 trace 相符。
  - 總計 input tokens 6,309、output tokens 78、total 6,387、duration 9.83 秒，model 為 `llama-3-3-70b-instruct`。
  - span 樹：`agent` → `llm.llama-3-3-70b-instruct` → `api.llama-3-3-70b-instruct`（第一次，2,888 tokens，6.22 秒）→ `web_search`（1.00 秒）→ `api.llama-3-3-70b-instruct`（第二次，3,499 tokens，2.50 秒）。
  - `api.*` span 在 wxO 顯示為 `GENERATION` 類型，並解析出 Model、Input/Output tokens、Input/Output 內容。
  - 最後一個 `api.*` span 的 attribute 同時帶 `agent.id` 與 `tenant.id`，Resource Attributes 帶 `tenant.id` 與 `deployment.environment: draft`，確認 Collector 兩層補值有效。
  - 結論：「wxO 只需 `agent.id`、`tenant.id`、`deployment.environment` 即可顯示 Hermes 的 trace」成立。
- **已觀察到的問題**：
  1. **User 顯示 `Unknown`**：Hermes 沒有送 `langfuse.user.id`。
  2. **`Show Reasoning` 等欄位的對應**：未逐項確認，待後續檢視。
  3. **`web_search` span 顯示為一般 span**（藍色），沒有被當成 tool 類型；`agent` 與 `llm.*` 也是一般 span。wxO 只有 `api.*` 被識別為 `GENERATION`。這與 hermes_otel 的 span 命名有關，是否需要調整未評估。
  4. **Analytics 數字可能含測試 span**：子任務 3 的 `collector-smoke-test`、`token-hotreload-test` 使用同一個 `agent.id`，可能影響 Overview 的對話數。
  5. **Podman 開機自動啟動：使用者決定不處理，改為手動啟動。** 查證結果：Podman machine 沒有 launchd 項目、Podman Desktop 的 `preferences.login.start` 為 `false`；VM 內 `podman-restart.service` 為 disabled，且該服務只拉起 `restart-policy=always` 的容器，而 `wxo-otelcol` 是 `unless-stopped`。以上都是依設定判斷，未實際重開機驗證；token 更新服務與 Hermes gateway 是否會在登入後自動回來同樣未驗證（gateway 的 launchd 項目顯示無 PID、退出碼 75）。手動啟動與逐項檢查流程見 [`docs/重開機後手動啟動流程.md`](docs/重開機後手動啟動流程.md)。

### 6. 收尾

- **Intent**：讓整套設定可重現且不外洩機密。
- **Expected Outcomes**：啟動順序與維運步驟有文件；機密不在版控。
- **Todo List**：
  1. 在專案內新增簡短操作說明（啟動 token 腳本、啟動 Collector、啟用 plugin）。
  2. 確認 `.env`、token 檔、API key 都被 `.gitignore` 排除（目前 git 狀態中已有 token 的 txt 檔未被忽略，需提醒使用者）。
  3. 記錄已知限制（content_capture 隱私、token 備案流程）。
- **Relevant Context**：`.gitignore`、本計畫檔。
- **Status**：`[ ] pending`

## 待驗證的假設

| 假設 | 驗證位置 | 驗證結果 |
|---|---|---|
| `bearertokenauth` 的 `filename` 在 Podman macOS 掛載下可熱更新 | 子任務 3 | **已驗證**：每次請求重讀檔案，`refresh_token.py --once` 後立即生效，無需重啟容器 |
| hermes_otel 的 `type: otlp` 可指向 localhost 並正常送出 traces | 子任務 4 | **已驗證**：`type: otlp`（或 `type: lgtm`）+ `endpoint` 完整 URL，gateway 啟動後立即送出；Collector 在 `10:01:24Z` 收到 3 ResourceSpans、5 spans，`otlphttp/wxo` 無 error |
| `TOKEN_URL` 回應格式與有效期 | 子任務 2 | 已實測驗證：IAM OAuth Bearer Token，有效期 3600 秒 (1hr) |
| wxO 只需 `agent.id`、`tenant.id`、`deployment.environment` 即可顯示 Hermes 的 trace | 子任務 5 | **已驗證**：Conversations 與 Trace view 皆顯示，`api.*` span 被識別為 GENERATION 並解析 token 與 input/output；User 欄位為 `Unknown` |
| 已有的 Hermes external agent 可否重用其 Agent ID | 子任務 1 | 已完成確認 |
