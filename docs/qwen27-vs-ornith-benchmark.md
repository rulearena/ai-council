# qwen27 (Qwen3.6-27B) vs Ornith-1.0-35B-GGUF 實測評分

srv-nas1 上自建的 14 題（9 抓 bug + 5 寫程式）評測，目的是判斷要不要把現役 Hermes provider `qwen27` 換成 `Ornith-1.0-35B-GGUF`。

- **qwen27**：`bartowski/Qwen_Qwen3.6-27B-GGUF`，Q4_K_M，dense 27B，llama.cpp，`-c 98304`。測了兩種模式：thinking 關閉（配合原本部署設定）、thinking 開啟。
- **Ornith**：`deepreinforce-ai/Ornith-1.0-35B-GGUF`，Q4_K_M，MoE 35B（~3B active），llama.cpp，`-c 32768`，thinking 開啟（模型預設行為；~~無法關閉測試~~ **更正：實測可關閉，見下方「2026-07-10 補充更正」，本次評測仍只跑了 thinking 模式**）。
- 評分方式：抓 bug 題人工比對根因＋修法是否正確（0-2 分/題）；寫程式題實際執行隱藏測試案例算通過率（0-5 分/題）

## 抓 Bug 題（滿分 18）

| 題號 | 內容 | qwen27（無 thinking）| qwen27（thinking）| Ornith-35B（thinking）| 備註 |
|---|---|---|---|---|---|
| B1 | mutable default argument | 2 | 2 | 2 | 三方平手 |
| B2 | binary search 死迴圈 | 1（診斷對但沒交出程式碼，燒光 3000 token）| 2 | 2 | thinking 模式下 qwen27 這題就修正了：正確推導出反例並交出程式碼 |
| B3 | race condition | 2 | 2 | 2 | 三方平手 |
| B4 | SQL injection | 2 | 2 | 2 | 三方平手，thinking 模式下 qwen27 也抓到次要 bug（`cursor` 未定義）|
| B5 | cache key 缺 currency | 2 | 2 | 2 | 三方平手 |
| B6 | command injection | 1（沒當成主要 bug）| 2 | 2 | thinking 模式下 qwen27 這題也修正了，明確列為第一重點 |
| B7 | insecure deserialization (pickle) | 2 | 2 | 2 | 三方平手 |
| B8 | SSRF | 0 | 0 | 0 | **三方都完全沒抓到**，都只講「沒做錯誤處理」，跟 thinking 開關無關，是共同盲點 |
| B9 | timing attack | 2 | 2 | 2 | 三方平手 |

**Bug 小計：qwen27 無 thinking 14/18　qwen27 thinking 16/18　Ornith 16/18**

## 寫程式題（滿分 25，實測執行隱藏測試案例）

| 題號 | 內容 | qwen27（無 thinking）| qwen27（thinking）| Ornith-35B（thinking）| 備註 |
|---|---|---|---|---|---|
| C1 | LRU Cache | 5（14/14）| 5（14/14）| 5（14/14）| 三方平手 |
| C2 | Log 解析 | 5（10/10）| 5（10/10）| 4（9/10）| Ornith regex 用 `\s+` 而非 `\s*`，`[WARN]` 後無內容時解析失敗，兩個 qwen27 版本都沒這問題 |
| C3 | Sliding Window Rate Limiter | 5（6/6）| 5（6/6）| 5（6/6）| 三方平手 |
| C4 | Merge Intervals | 5（5/5）| 5（5/5）| 5（5/5）| 三方平手 |
| C5 | 安全檔案讀取（防 Path Traversal）| 5（6/6）| 5（6/6）| 5（6/6，見下方「C5 重測」）| 三方最終都拿到滿分，過程見備註 |

**寫程式小計：qwen27 無 thinking 25/25　qwen27 thinking 25/25　Ornith 24/25**

## 總分

| 版本 | 總分 | 百分比 |
|---|---|---|
| qwen27（無 thinking，目前實際部署設定）| 39/43 | 91% |
| **qwen27（開啟 thinking）** | **41/43** | **95%** |
| Ornith-35B（thinking，唯一模式）| 40/43 | 93% |

**開啟 thinking 後 qwen27 是三者中分數最高的**——B2、B6 兩題原本因為推理不夠深入而扣分，開 thinking 後都修正了，且沒有引入新的失誤。

## 速度對照（wall-clock 與 token 生成速度）

| 版本 | 平均生成速度 | 平均每題耗時 |
|---|---|---|
| qwen27 無 thinking | ~22-23 tokens/sec | ~25 秒 |
| qwen27 開 thinking | ~23 tokens/sec（不變）| **~125 秒**（約 5 倍慢，因為多輸出大量 `<think>` 推理內容）|
| Ornith（thinking）| ~112 tokens/sec | ~20-60 秒（少數題目較久）|

**關鍵發現**：qwen27 的原始生成速度（tokens/sec）不受 thinking 開關影響，純粹是「thinking 模式下要多生成好幾倍的 token」讓等待時間變長。Ornith 因為是 MoE（只有 ~3B active），生成速度比 qwen27 快 5 倍，即使同樣要跑完整的 thinking 推理，實際等待時間還是比 qwen27 開 thinking 短很多。**如果決定要用 thinking 模式，Ornith 在延遲上有明顯優勢；如果 qwen27 維持關閉 thinking，兩者延遲相近，但 qwen27 的分數會比開 thinking 時低（39 vs 41）。**

### C5 重測細節（Ornith）

Ornith 容器最初用 `-c 8192` 部署，這題需要仔細推理多種繞法（`..`、絕對路徑、symlink），reasoning 還沒收斂 context 就用完，兩次嘗試（max_tokens 6000 和 12000）都在句子中間被硬切斷，程式碼不完整。把容器 context 加大到 `-c 32768`（VRAM 只多花約 500MB，證實 hybrid 架構 KV cache 確實很省）後重測，模型花了 20768 token 做 reasoning、59.8 秒，最終給出完整正確的實作（`os.path.realpath` 解析 symlink + `os.sep` 前綴檢查），6/6 測試全過。

**結論**：這不是模型能力問題，是部署設定（context window 太小）沒抓對。

## 重要發現

1. **thinking 對 qwen27 是淨正值**：兩題（B2、B6）從錯誤修正為正確，沒有任何一題因為開 thinking 而變差，唯一代價是延遲增加約 5 倍。
2. **SSRF（B8）是三方共同盲點**，跟 thinking 開關無關——不管哪個版本、哪個模型，都把「伺服器端請求任意網址」當成單純的錯誤處理問題，完全沒有意識到 SSRF 風險。如果要拿任何一個模型做 code review，這類「網址即輸入」的漏洞需要額外提醒或用其他工具補強。
3. **「燒光 token 交不出答案」的失敗模式**：qwen27 無 thinking 時在 B2 發生過（自我驗證方法有誤）；Ornith 初測 C5 也發生過，但追查後是我部署時 context window 設太小（8192）導致，加大 context 後就正常收斂。開 thinking 的 qwen27 這次沒有再出現這個問題。提醒：遇到模型「answer 沒生完」時，先檢查是不是自己的 context/token 上限設太小，再判斷是不是模型本身的問題。
4. **VRAM**：Ornith 在 32768 context 下用約 21GB；qwen27 在 98304 context 下用約 23.3GB（不受 thinking 開關影響，因為 VRAM 用量取決於 context 大小，不是輸出內容多寡）。

## 2026-07-10 補充更正（thinking 控制方式 + content/reasoning_content 欄位）

*by 另一個 Claude Code session（2026-07-10 實測補充）。原報告把「thinking 燒光 token 交不出答案」框成 token 上限問題（對了一半），但（a）沒點破這其實是 API 欄位分流、（b）誤判 Ornith 的 thinking 關不掉。以下更正。*

### 為什麼 coding agent 會拿到「空的 content」

兩個模型 thinking **預設開**。llama.cpp 正確地把**思考內容放 `reasoning_content`、最終答案放 `content`**——content 不是壞的。問題有兩層疊加：

1. thinking 很囉唆：連「寫費氏數列」都先燒 ~600-800 token 思考，答案才 30-50 token
2. 一般 coding agent 的 max_tokens 常設 512/1024 → **還在 thinking 就被截斷**（`finish_reason=length`）→ `content` 全空，agent 只讀 content 就抓不到東西

實測（2026-07-10，同一題「寫費氏數列」）：

| 設定 | content | reasoning_content | finish | 結果 |
|---|---|---|---|---|
| 預設 thinking，max_tokens=800 | 空 | 2400+ 字 | length | ❌ 截斷在思考 |
| 預設 thinking，max_tokens=3000 | 有 | 2000+ 字 | stop | ✅ 給夠 token 才吐 content |
| **請求帶 `enable_thinking:false`** | 有 | 0 | stop | ✅✅ 乾淨即答、零浪費 |
| prompt 加 `/no_think` | qwen27 空 / ornith 半 | 2500+ | length | ❌ 不可靠 |

### 可靠的關法（qwen27 與 ornith 都實測有效）

請求 body 加：
```json
{ "model": "...", "messages": [...], "chat_template_kwargs": { "enable_thinking": false } }
```
OpenAI SDK 風格：`extra_body={"chat_template_kwargs": {"enable_thinking": false}}`。
→ content 立刻有答案、reasoning 空、`finish=stop`，簡單任務 token 省約 10 倍、快很多。**對 coding agent 建議預設就關。**

⚠️ **`/no_think` 別用**——qwen27 完全無效、ornith 只有一半有效，不可靠。

### 若要保留 thinking

max_tokens 至少給 **6000+**（跟本報告第 105 行的提醒一致），而且 agent 端要改讀 `reasoning_content`，或等 thinking 收斂後才出現的 `content`——不能只讀 content 配小 max_tokens。

---

## 目前伺服器狀態（2026-07-07 15:22 更新）

**Hermes 正式已切換到 Ornith**，兩種用法都在跑：

| 用途 | 方式 | 說明 |
|---|---|---|
| 日常對話（走 SOUL.md）| Open WebUI（`http://srv-nas1:3000`，選 `hermes-agent`）或 Telegram | Hermes gateway (port 8642) 現在預設 provider 是 `ornith` |
| API vibe coding（跳過 SOUL.md）| 直連 `http://192.168.50.81:8488/v1/chat/completions` | 完全繞過 Hermes，純模型，已驗證沒有 Hermes 人格 |

**Ornith 容器設定**：`srv-nas1:/home/user/docker/ornith/docker-compose.yml`，port 8488，`-c 131072 -np 2`（每個併發 slot 65536 context）。

context 從一開始的 8192 → 32768 → 最後拉到 65536/slot，是因為 **Hermes 強制要求 model context_length 至少 64K** 才能當 Hermes Agent 的後端模型（低於這個門檻會直接報錯拒絕）。同時考慮到 Hermes 對話 + 直接 API 呼叫可能同時有人在用，設了 `-np 2` 併發。

**VRAM 現況**：23044MB／24576MB 已用，只剩約 **1GB 餘裕**，偏緊。如果兩個併發 slot 同時被長對話占滿，有 OOM 風險，之後如果覺得不穩定，可以考慮降回 `-np 1` 換取更大安全邊際。

**qwen27 容器目前是停止狀態**（VRAM 讓給 Ornith，同一張 3090 一次只能跑一個 27B/35B 級模型）。Hermes config 的 `model.provider` 已改成 `ornith`，qwen27 的 provider 設定還留在 config 裡（`http://localhost:8487/v1`），之後要切換回去只需要重啟 qwen27 容器 + 把 `model.provider` 改回 `qwen27`。

**已知副作用**：停 qwen27 期間，任何寫死指向 `bartowski/Qwen_Qwen3.6-27B-GGUF` @ `localhost:8487` 的 cron job（例如 `web-content-monitor`）會持續失敗，因為它們不吃 Hermes 的 `model.provider` 全域預設，是各自寫死 model/endpoint。如果決定長期用 Ornith，這些 cron job 需要一併更新。

## 這份文件作為未來評測基準

之後測試其他開源模型時，重複使用同一套 14 題題庫與評分腳本，才能跟這次的分數直接比較：

- **題庫 + 送出腳本**：`scripts/llm_benchmark/questions.py`、`scripts/llm_benchmark/run.py`
  ```bash
  cd scripts/llm_benchmark
  python3 run.py <api_url> <model_name> <output.json> [max_tokens]
  # 例：python3 run.py http://192.168.50.81:8488/v1/chat/completions deepreinforce-ai/Ornith-1.0-35B-GGUF results.json 6000
  ```
- **寫程式題自動評分**：`scripts/llm_benchmark/hidden_tests/grade.py`
  ```bash
  python3 scripts/llm_benchmark/hidden_tests/grade.py <output.json>
  ```
  會印出 C1-C5 各題通過率與 /25 總分。
- **抓 bug 題（B1-B9）沒有自動化**，需要人工比對「有沒有抓到根因＋修法是否正確」，評分標準 0-2 分/題，可參考本文件「抓 Bug 題」表格裡各家模型的答案品質當作對照基準。
- **重要提醒**：如果新模型是「thinking」型（會輸出 `<think>` 推理），max_tokens 至少給到 6000 起跳，且部署時 context window 不要設太小（本次 Ornith 就因為一開始 `-c 8192` 太小，燒光 token 卻交不出程式碼，加大到合理值後才拿到正確答案——遇到「answer 沒生完」先懷疑自己的部署設定，不要急著判模型能力不足）。

### 完整題目（供人工核對／重跑用）

**抓 Bug 題共用 prompt 模板**：「以下 Python 程式碼有一個 bug，請找出 bug 在哪裡、解釋為什麼會出問題、並提供修正後的完整程式碼。」+ 下列程式碼：

| 題號 | 程式碼片段 | 意圖考察的 bug 類型 |
|---|---|---|
| B1 | `def add_item(item, basket=[]): basket.append(item); return basket` | mutable default argument |
| B2 | `binary_search`，`elif arr[mid] < target: lo = mid`（應為 `lo = mid + 1`）| 死迴圈／off-by-one |
| B3 | 4 條 thread 各自 `counter += 1` 100000 次，無 lock | race condition |
| B4 | `query = f"SELECT * FROM users WHERE username = '{username}'"` | SQL injection |
| B5 | `cache[product_id] = price`，忽略 `currency` 參數 | cache key 不完整 |
| B6 | `os.system(f"ping -c 1 {host}")` | command injection |
| B7 | `pickle.loads(data)` | insecure deserialization |
| B8 | `requests.get(url, timeout=5)`，`url` 為外部輸入 | SSRF |
| B9 | `return user_token == real_token` | timing attack |

**寫程式題**（完整需求文字見 `scripts/llm_benchmark/questions.py` 的 `CODING` dict）：

| 題號 | 題目 |
|---|---|
| C1 | 實作 O(1) get/put 的 LRU Cache |
| C2 | 解析格式不完全一致的 log line（含引號字串、malformed line 要回傳 None）|
| C3 | Thread-safe sliding window rate limiter |
| C4 | Merge overlapping intervals，並註解說明相鄰區間的假設 |
| C5 | 防 Path Traversal 的安全檔案讀取（含 symlink 逃逸測試）|

## 待決定

1. Hermes 正式要長期用哪個 provider？目前已切到 Ornith，但分數最高的其實是 **qwen27 開 thinking**（41/43），只是延遲高 5 倍——如果延遲可以接受，值得重新評估。
2. SSRF 盲點（B8）三方都沒抓到，是否需要額外的安全掃描工具補強，不能只靠 LLM code review。
3. VRAM 只剩 ~1GB 餘裕，長期穩定性有疑慮，必要時把 `-np` 降回 1。

---
*本文件為持續更新的評測記錄與基準題庫，後續測試其他開源模型的結果會陸續補充在對應章節。*
