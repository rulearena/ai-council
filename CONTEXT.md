# AI Council

單一情境產品：讓使用者以「AI 委員會／法庭／聊天室」等多種會議模式，與多個 AI 角色開會、攻防、判決，並透過版本化案卷與附件提供模型 grounding。

## Language

**附件（Attachment）**：
使用者透過聊天室 composer `+` 按鈕上傳的檔案。二進位 blob 存於 data-dir 的附件目錄，metadata（檔名、大小、MIME、file_id）以事件形式存進 `events.jsonl`，下載以 file_id 查詢真實路徑。
_Avoid_: 上傳檔案、附件檔

**案卷（Case Materials）**：
既有版本化的純文字證據與案件備註，含可見角色與字元上限，注入 prompt 供 AI 讀取。與附件不同源：案卷是文字、附件是二進位 blob。
_Avoid_: 證物（法院語境專用別名）、附件

**共享會議記憶（Shared Meeting Memory）**：
限定在單一會議內、由人類訊息與 AI 回覆共同形成的公開脈絡；所有角色可依當次上下文選擇規則參照它。
_Avoid_: 個別 AI 記憶、私有記憶

**共享會議摘要（Shared Meeting Summary）**：
從完整會議 transcript 壓縮出的共享脈絡，供長對話在有限上下文中延續重要事實、決策與未解問題；它不是另一位 AI 的發言。
_Avoid_: AI 私人摘要、摘要回覆

**角色 Persona**：
角色穩定的身分、觀點與對話行為，與共享會議記憶分開定義；它決定角色如何回應，不是角色私自保存的對話內容。
_Avoid_: 角色記憶、角色背景

**固定聊天室角色（Fixed Chatroom Role）**：
聊天室內建且不可由單一會議改寫的主持 AI、顧問、評論者、策略師與分析師；每個角色都有穩定的 Persona。
_Avoid_: 預設角色、自訂角色

**啟用聊天室角色（Active Chatroom Role）**：
從固定或自訂角色中加入單一會議、可被 `@` 與 `@all` 呼叫的參與者；主持 AI 必定啟用，其餘固定角色在建立會議時由使用者選擇，建立後名單維持不變。
_Avoid_: 全部固定角色、可用角色

**自訂聊天室角色（Custom Chatroom Role）**：
使用者為單一會議建立的角色，名稱、Persona 與模型可自訂；其 Persona 是低於產品規則的使用者內容，不能改寫系統安全、路由、來源授權或輸出契約。
_Avoid_: 自訂 system prompt、無限制角色 prompt

**原生開發層支援（Native Developer-Role Support）**：
AI 連接器能否以服務原生格式分開傳送 system、developer、user 三層訊息；這是連接器的能力，不是會議或模型的個別設定。
_Avoid_: 模型個別開關、會議層支援

**標準提示紀錄（Canonical Prompt Audit）**：
聊天室在服務轉換前保存的 system、developer、user 三層原始提示紀錄；它不隨 AI 供應商實際傳輸格式改變。
_Avoid_: 供應商請求紀錄、合併後提示紀錄

**自然回覆契約（Natural Reply Contract）**：
聊天室 AI 以直接、連貫的對話訊息回答當前問題，不要求固定的報告欄位或標題；結構化格式只屬於傳輸層，不是使用者看到的語氣。
_Avoid_: 報告式回覆、固定四段式回覆

**附件引用（Attachment Reference）**：
使用者在聊天室訊息中以 `#` 明確選取的附件參照；只有被引用且 AI 可讀的附件正文才可成為該次回覆的上下文。
_Avoid_: 自動帶入附件、附件全文注入
