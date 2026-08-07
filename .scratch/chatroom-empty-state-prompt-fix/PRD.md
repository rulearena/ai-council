# #102 聊天室初始空白提示修正

Status: implemented / awaiting Human Owner acceptance (2026-08-07)

## 問題

聊天室沒有任何訊息時，`ConversationWorkspace` 仍顯示一般會議的共用提示：

> 尚未有會議發言；可先記錄主席補充，或啟動第一次審議。

聊天室沒有自動啟動第一次審議的流程；AI 只有在主席使用 `@角色` 或 `@all` 時才會回應，因此這段提示會誤導使用者。

## 固定行為契約

- chatroom 空白訊息串顯示：`還沒有訊息；可直接輸入文字，想請 AI 回應時請 @角色 或 @all。`
- chatroom 的初始提示不得出現「啟動第一次審議」或其他固定流程用語。
- 非 chatroom 模式維持既有空白提示不變。
- 已選取角色但該角色沒有發言時，既有「這個角色還沒有發言。」提示不變。
- 只修改前端呈現文案，不改 API、事件格式、mention 語意、AI 執行流程或歷史資料。

## 驗收項目

1. 新建聊天室且尚未有訊息時，看到上述 chatroom 專用提示。
2. 該提示不包含「啟動第一次審議」。
3. 非聊天室空白工作區仍顯示原有提示。
4. 角色篩選為空時仍顯示既有角色專用提示。

## 驗證方式

- 以 Playwright Chromium 覆蓋 chatroom 初始空白畫面與非 chatroom 回歸。
- 執行 frontend unit、frontend build、`git diff --check`。

## 排除範圍

- 不處理一般文字是否自動觸發 AI。
- 不處理角色個性、回覆格式或 ChatGPT 式聊天互動；這些留待後續 `grill-with-docs` 需求討論。
