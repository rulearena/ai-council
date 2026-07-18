# 05 — Responsive integration, review and delivery

Type: task
Status: ready
Blocked by: 03, 04

## 目標

完成 responsive polish、完整 regression gates、獨立雙軸 review、main merge 與清理。

## 驗證

- Relay：發言時間序、role filter、long collapse、materials drawer、reload。
- Parallel：partial arrival、thinking state、arrival order reload、synthesis last。
- Courtroom：docket／arguments／ruling／next／final 不 reload。
- 375px：角色列、feed、context 與 composer 無不可達操作。
- Backend full、frontend unit、build、full Chromium、direct browser smoke。

## 禁止事項

- 不合併 prototype branch；正式功能依 production architecture 重建。
- 不提交或覆寫 `config/models.yaml.example` 的 Human Owner 變更。
