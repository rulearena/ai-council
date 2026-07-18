# 04 — Court Hearing presentation

Type: task
Status: ready
Blocked by: 02

## 目標

法院共用 workspace shell，但中央按爭點／攻防階段呈現，正式流程 CTA 固定在右側並完全採用 backend `available_actions`。

## 行為

- 不把法院攻防偽裝成自由聊天。
- Composer 僅允許記錄補充與 backend 支援的指定角色補充；不裁定、不推進。
- current issue、已完成 rulings、final verdict 與 blocked reason 容易辨識。
- 等待主席時顯示精確下一步，不恢復已淘汰的重複 action selector。

## 完成條件

- Civil／criminal、reload、next issue、final gate 的 targeted Playwright 綠。
