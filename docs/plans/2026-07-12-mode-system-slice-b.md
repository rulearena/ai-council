# Mode System Slice B（relay 參數化 + GET /modes + courtroom/debate 上線）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（或 subagent-driven-development）task-by-task 實作本計畫。

**Goal:** 後端支援宣告式會議模式（`config/modes.yaml` + `GET /modes`），relay 執行器由 mode 設定驅動，`POST /meetings` 接受 `mode_id`/`participants`/`inputs`，前端切換到後端 catalog 並讓「法庭審理」「辯論」兩個模式可實際建立與執行。

**Architecture:** 模式是設定不是程式碼（spec.md §16.1）。新增 `ai_council/meetings/modes.py`（yaml 解析 + 驗證 + RelayPlan 推導）；`MeetingRunner` 移除寫死的 `STEPS`/`DIRECTED_RESPONSE_STEPS`，改由每次呼叫傳入 `RelayPlan`；API 層依 meeting metadata 的 `mode_id` 解析 mode → plan → runner。前端 `modes.ts` 本地 catalog 降級為 fallback，改由 `GET /modes` 餵資料；`useCouncil.ts` 的 active mode 從模組常數改為「跟著選中的 meeting 走」。

**Tech Stack:** FastAPI + PyYAML + pytest（backend）；Vue 3 + TypeScript + Playwright（frontend）。

**向後相容鐵則（spec §16.3/16.5）：**
- 既有 events.jsonl 的 step_id（`blue-propose`/`red-critique`/`blue-revise`/`judge-decide`、`round-N-*`、`*-response`）一個都不能變。
- 無 `mode_id` 的舊會議一律投影為 `red-blue` + 現行三角色 participants。
- 共用 output schema（§8）不變。

**慣例：** step_id = template 名稱把 `_` 換成 `-`（`courtroom_charge` → step_id `courtroom-charge`）。directed response step_id = `{role小寫}-response`，template 取該角色在 steps 中**最後一個** step 的 template（red-blue 驗證：Blue→`blue_revise` ✓、Red→`red_critique` ✓、Judge→`judge_decide` ✓，與現行行為完全一致）。

**執行環境：**
- Worktree：`/Users/chrischiu/SynologyDrive/Project/AI_Council-worktrees/mode-system-slice-b`（branch `mode-system-slice-b`）
- 後端測試：`cd backend && .venv/bin/python -m pytest tests/ -q`（若 .venv 不在 worktree，先 `python3 -m venv .venv && .venv/bin/pip install -e . pytest httpx` 或直接用主 repo 的 venv 路徑跑）
- 前端：`cd frontend && npm install && npm run build`；e2e：`npm run test:e2e`（先看 `playwright.config.ts` 確認它怎麼起後端）

---

## Phase 1 — Backend

### Task 1: Prompt 模板改名（red→red_critique、judge→judge_decide）

讓 prompt 檔名與 spec §16.2 / 前端 catalog 的 template 名一致，才能套用「step_id = template 名」慣例。事件裡的 step_id 本來就是 `red-critique`/`judge-decide`，**不變**；變的只有 `prompt_template_name` 欄位值（只影響新事件，舊事件照舊，無相容問題）。

**Files:**
- Rename: `prompts/red.md` → `prompts/red_critique.md`
- Rename: `prompts/judge.md` → `prompts/judge_decide.md`
- Modify: `backend/ai_council/meetings/runner.py:50-61`（STEPS/DIRECTED_RESPONSE_STEPS 的 template 名）
- Modify: `backend/tests/test_meeting_runner.py`（TEST_PROMPT_TEMPLATE_HASHES、所有 `"red"`/`"judge"` template 斷言）
- Modify: `backend/tests/test_api.py:1313`（create_test_app 的 template 清單）

**Step 1:** `git mv prompts/red.md prompts/red_critique.md && git mv prompts/judge.md prompts/judge_decide.md`

**Step 2:** runner.py 中 `StepDefinition("red-critique", "Red", "red")` → `..., "red_critique")`；`StepDefinition("judge-decide", "Judge", "judge")` → `..., "judge_decide")`；DIRECTED_RESPONSE_STEPS 同步（`"red"`→`"red_critique"`、`"judge"`→`"judge_decide"`）。

**Step 3:** 更新測試。test_meeting_runner.py 的測試模板內容是 `f"{template} {{ role }} ..."`，改名後內容變 → hash 變。先跑一次測試讓它 fail，從 fail 訊息或用下面指令重算 hash 填回：

```bash
cd backend && .venv/bin/python -c "
import hashlib
for t in ['blue_propose','red_critique','blue_revise','judge_decide']:
    content = f'{t} {{{{ role }}}} {{{{ topic }}}} {{{{ prior_transcript }}}} {{{{ required_json_schema }}}}'
    print(t, hashlib.sha256(content.encode()).hexdigest())
"
```

同時 grep 兩個測試檔中的 `"red"`、`"judge"`（template 名語境，不是 role 名！role 仍是 `Red`/`Judge`）與 `red.md`/`judge.md` 字樣逐一修正。test_api.py `create_test_app` 的清單改為 `["blue_propose", "red_critique", "blue_revise", "judge_decide"]`。

**Step 4:** `cd backend && .venv/bin/python -m pytest tests/ -q` → 全綠。

**Step 5:** `git add -A && git commit -m "refactor: rename prompt templates to match mode catalog names"`

### Task 2: PromptRenderer 支援 mode inputs 注入（TDD）

辯論模式的 `position_a`/`position_b` 要能進 prompt。

**Files:**
- Modify: `backend/ai_council/prompting/renderer.py`
- Test: `backend/tests/test_prompting.py`

**Step 1: 寫 failing test**（加入 test_prompting.py，比照該檔既有 renderer 測試的 fixture 寫法——先讀該檔，沿用其建模板暫存檔的 helper）：

```python
def test_renderer_injects_mode_inputs(tmp_path: Path) -> None:
    (tmp_path / "debate_statement_pro.md").write_text(
        "{{ topic }} | {{ position_a }} vs {{ position_b }}", encoding="utf-8"
    )
    renderer = PromptRenderer(tmp_path)

    rendered = renderer.render(
        template_name="debate_statement_pro",
        role="Pro",
        topic="T",
        prior_transcript="",
        required_json_schema="{}",
        inputs={"position_a": "先做後端", "position_b": "先做前端"},
    )

    assert rendered == "T | 先做後端 vs 先做前端"


def test_renderer_builtin_values_win_over_inputs(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text("{{ topic }}", encoding="utf-8")
    renderer = PromptRenderer(tmp_path)

    rendered = renderer.render(
        template_name="t",
        role="Pro",
        topic="real",
        prior_transcript="",
        required_json_schema="{}",
        inputs={"topic": "hijacked"},
    )

    assert rendered == "real"
```

**Step 2:** 跑 `pytest tests/test_prompting.py -q` → FAIL（unexpected keyword `inputs`）。

**Step 3: 實作** — `render()` 加 `inputs: dict[str, str] | None = None` 參數：

```python
        values = {
            **{key: str(value) for key, value in (inputs or {}).items()},
            "role": role,
            "topic": topic,
            "prior_transcript": prior_transcript,
            "required_json_schema": required_json_schema,
        }
```

**Step 4:** `pytest tests/test_prompting.py -q` → PASS；全套 `pytest tests/ -q` → 綠。

**Step 5:** `git add -A && git commit -m "feat: prompt renderer accepts per-meeting mode inputs"`

### Task 3: 新增 9 個 relay prompt 檔（courtroom ×4、debate ×5）

**Files（Create）：** `prompts/courtroom_charge.md`、`prompts/courtroom_defense.md`、`prompts/courtroom_rebuttal.md`、`prompts/courtroom_verdict.md`、`prompts/debate_statement_pro.md`、`prompts/debate_statement_con.md`、`prompts/debate_cross_pro.md`、`prompts/debate_cross_con.md`、`prompts/debate_verdict.md`

全部沿用 `prompts/red_critique.md` 的既有結構（英文鷹架 + `{{ topic }}`/`{{ prior_transcript }}`/`{{ required_json_schema }}` 佔位符 + 「Respond in the same language as the meeting topic」語言規則）。範例（courtroom_charge.md）：

```markdown
You are the Prosecutor role in an AI Council courtroom hearing.

The topic below is the incident, design, or decision on trial. Treat it as the defendant.

Topic:
{{ topic }}

Prior transcript:
{{ prior_transcript }}

Task:
Present the charges. Enumerate every specific failure, flawed assumption, negligent omission, and contributing cause you can identify in the matter on trial. Each charge must be concrete and falsifiable, not a vague accusation.

Language:
Respond in the same language as the meeting topic.
All JSON string values must use that language.

Return exactly one JSON object matching this schema:
{{ required_json_schema }}
```

其餘八個檔案的 Task 段落要點（開頭 role 行與結構同上，逐檔改 role 名）：
- **courtroom_defense**（Defense）：針對 Prosecutor 的每一條指控逐條答辯——承認站得住的、反駁證據不足的、補充脈絡與外部限制；不得迴避任何一條指控。
- **courtroom_rebuttal**（Prosecutor）：閱讀辯方答辯後再質詢——指出哪些答辯站不住、哪些指控被實質化解、追加新事證。
- **courtroom_verdict**（Judge）：綜合控辯雙方，逐條裁定每項指控成立與否，給出最終判決與具體改善令（recommendation 欄位）。
- **debate_statement_pro**（Pro）：模板需含 `Your assigned position:\n{{ position_a }}`（在 Topic 段之後）。為 position_a 做開場申論：最強論據、證據、預期反方攻擊點的預防性回應。
- **debate_statement_con**（Con）：同上但 `{{ position_b }}`。
- **debate_cross_pro**（Pro）：含 `{{ position_a }}`。針對反方申論做交叉質詢：拆解其論據的假設漏洞。
- **debate_cross_con**（Con）：含 `{{ position_b }}`。針對正方申論與質詢做交叉質詢。
- **debate_verdict**（Arbiter）：模板需同時含 `Position A:\n{{ position_a }}` 與 `Position B:\n{{ position_b }}`。裁定哪一方立場更站得住腳、在什麼條件下結論會翻轉。

**驗證：** 每個檔案都包含 `{{ topic }}`、`{{ prior_transcript }}`、`{{ required_json_schema }}`；debate 五檔含正確的 position 佔位符。`grep -L "required_json_schema" prompts/*.md` 應無輸出。

**Commit:** `git add prompts && git commit -m "feat: add courtroom and debate prompt templates"`

### Task 4: `config/modes.yaml` + mode catalog 模組（TDD）

**Files:**
- Create: `config/modes.yaml`
- Create: `backend/ai_council/meetings/modes.py`
- Modify: `backend/ai_council/meetings/runner.py`（加 `RelayPlan` dataclass，緊接在 `StepDefinition` 之後；**runner 不 import modes.py**，避免循環相依——modes.py 反過來 import runner 的 `StepDefinition`/`RelayPlan`）
- Test: `backend/tests/test_mode_catalog.py`（新檔）

**Step 1: `config/modes.yaml`**（直接進版控，這是應用設定不是密鑰；欄位 snake_case 依 spec §16.2，step 加 `label` 供前端顯示）：

```yaml
modes:
  - id: red-blue
    name: 紅藍對抗
    category: relay
    tagline: 藍軍提案、紅軍質詢、裁判定案 —— 最扎實的方案壓力測試。
    when_to_use: 需要對單一方案做深度攻防、揪出被忽略的風險與反例時使用。
    sop:
      - 輸入要被驗證的方案主題
      - 為藍軍/紅軍/裁判挑選模型
      - 開始審議，觀察紅軍指出的缺陷
      - 對裁決不滿可追問或開新回合
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Blue, name: 藍軍, color: "#4d8dff", portrait: blue, kind: member }
      - { id: Red, name: 紅軍, color: "#ff6b5e", portrait: red, kind: member }
      - { id: Judge, name: 裁判, color: "#e8b44c", portrait: judge, kind: adjudicator }
    steps:
      - { role: Blue, template: blue_propose, label: 藍軍提案 }
      - { role: Red, template: red_critique, label: 紅軍質詢 }
      - { role: Blue, template: blue_revise, label: 藍軍修訂 }
      - { role: Judge, template: judge_decide, label: 裁判裁決 }

  - id: courtroom
    name: 法庭審理
    category: relay
    tagline: 像一場真實庭審一樣，逐條指控、逐條辯護，逼近事故或架構決策的真相。
    when_to_use: 適合災難覆盤、複雜架構除錯 —— 把「被審理的事故/設計」當被告，交互詰問到水落石出。
    sop:
      - 輸入要被審理的事故或架構決策
      - 為檢察官/辯護律師/法官挑選模型
      - 開始審理，依序觀察指控、辯護、再質詢
      - 參考法官判決；對判決不滿可追問或開新回合
    default_scene: courtroom
    inputs: []
    roles:
      - { id: Prosecutor, name: 檢察官, color: "#ff6b5e", kind: member }
      - { id: Defense, name: 辯護律師, color: "#4d8dff", kind: member }
      - { id: Judge, name: 法官, color: "#e8b44c", kind: adjudicator }
    steps:
      - { role: Prosecutor, template: courtroom_charge, label: 檢察官指控 }
      - { role: Defense, template: courtroom_defense, label: 辯護律師答辯 }
      - { role: Prosecutor, template: courtroom_rebuttal, label: 檢察官再質詢 }
      - { role: Judge, template: courtroom_verdict, label: 法官判決 }

  - id: debate
    name: 辯論
    category: relay
    tagline: 正反雙方各自申論、交叉質詢，仲裁人裁定哪條路線更站得住腳。
    when_to_use: 適合在兩條明確對立的路線（position A vs. B）間做決策時使用。
    sop:
      - 輸入正方/反方各自的立場
      - 為正方/反方/仲裁人挑選模型
      - 開始辯論，依序觀察申論與交叉質詢
      - 參考仲裁人裁決；對裁決不滿可追問或開新回合
    default_scene: meeting-room
    inputs:
      - { id: position_a, label: 正方立場, kind: text }
      - { id: position_b, label: 反方立場, kind: text }
    roles:
      - { id: Pro, name: 正方, color: "#4d8dff", kind: member }
      - { id: Con, name: 反方, color: "#ff6b5e", kind: member }
      - { id: Arbiter, name: 仲裁人, color: "#e8b44c", kind: adjudicator }
    steps:
      - { role: Pro, template: debate_statement_pro, label: 正方申論 }
      - { role: Con, template: debate_statement_con, label: 反方申論 }
      - { role: Pro, template: debate_cross_pro, label: 正方質詢 }
      - { role: Con, template: debate_cross_con, label: 反方質詢 }
      - { role: Arbiter, template: debate_verdict, label: 仲裁人裁決 }

  - id: brainstorm
    name: 腦力激盪
    category: parallel
    tagline: 多位委員同時發散思考，主持人彙整出共識、分歧與結論。
    when_to_use: 適合早期發散、廣度優先探索多種可能性的場合，而非驗證單一方案。
    sop:
      - 輸入要腦力激盪的主題
      - 決定委員人數（2–6 位），可為每位委員指定自訂視角
      - 為所有委員與主持人挑選模型
      - 開始討論，等待全部委員完成後觸發彙整
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Moderator, name: 主持人, color: "#8b6dd9", kind: synthesizer }
    fanout:
      role: Member
      template: brainstorm_member
      label: 委員發想
      min_instances: 2
      max_instances: 6
      instance_prompt: true
    synthesis: { role: Moderator, template: brainstorm_synthesis, label: 主持人彙整 }

  - id: six-hats
    name: 六頂思考帽
    category: parallel
    tagline: 白/紅/黑/黃/綠五頂帽子各司其職同時發言，藍帽統整成一份完整報告。
    when_to_use: 適合需要系統性覆蓋事實、直覺、風險、樂觀、創意五種視角，不遺漏任何一面時使用。
    sop:
      - 輸入要討論的主題
      - 為五頂帽子與藍帽統整挑選模型
      - 開始討論：白/紅/黑/黃/綠帽同時發言
      - 等待五頂帽子完成後，查看藍帽統整報告
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: HatWhite, name: 白帽（事實數據）, color: "#e8e8ec", kind: member }
      - { id: HatRed, name: 紅帽（直覺感受）, color: "#ff6b5e", kind: member }
      - { id: HatBlack, name: 黑帽（風險批判）, color: "#8a8f9c", kind: member }
      - { id: HatYellow, name: 黃帽（價值樂觀）, color: "#f0c05a", kind: member }
      - { id: HatGreen, name: 綠帽（創意發想）, color: "#3dd68c", kind: member }
      - { id: HatBlue, name: 藍帽（流程統整）, color: "#4d8dff", kind: synthesizer }

  - id: persona-testing
    name: 盲測用戶
    category: parallel
    tagline: 一群使用者輪番對產品/方案做出真實反應，產品顧問彙整成一份可行動的報告。
    when_to_use: 適合在正式上線或投放前，快速蒐集不同用戶輪廓對方案的第一反應。
    sop:
      - 輸入要盲測的產品或方案描述
      - 定義每個 persona 的名稱與描述（2–6 位）
      - 為所有 persona 與產品顧問挑選模型
      - 開始測試，等待全部 persona 反應完成後查看彙整報告
    default_scene: meeting-room
    inputs:
      - { id: personas, label: Persona 清單（名稱＋描述）, kind: persona-list }
    roles:
      - { id: ProductAdvisor, name: 產品顧問, color: "#8b6dd9", kind: synthesizer }
    fanout:
      role: Persona
      template: persona_member
      label: Persona 反應
      min_instances: 2
      max_instances: 6
      instance_prompt: true
    synthesis: { role: ProductAdvisor, template: persona_synthesis, label: 產品顧問彙整 }
```

（內容抄自前端 `frontend/src/modes.ts` 既有文案，兩邊必須逐字一致。）

**Step 2: failing tests**（`backend/tests/test_mode_catalog.py`）——測試自行寫最小 yaml 到 tmp_path（比照 ModelConfigRepository 測試慣例），涵蓋：

```python
def test_catalog_parses_relay_mode(tmp_path): ...
    # list_modes() 回傳 ModeDefinition；欄位齊全；relay mode available == True

def test_catalog_marks_parallel_modes_unavailable(tmp_path): ...
    # category: parallel → available == False（slice C 前）

def test_relay_plan_derives_step_ids_from_templates(tmp_path): ...
    # steps template courtroom_charge → StepDefinition("courtroom-charge", "Prosecutor", "courtroom_charge")

def test_relay_plan_directed_steps_use_last_template_per_role(tmp_path): ...
    # 兩個 Blue steps（blue_propose、blue_revise）→ directed_steps["Blue"].template == "blue_revise"
    # directed_steps["Blue"].step_id == "blue-response"

def test_relay_plan_rejects_parallel_mode(tmp_path): ...
    # relay_plan(parallel mode) raises ModeConfigError

def test_catalog_rejects_step_role_not_in_roster(tmp_path): ...
def test_catalog_rejects_duplicate_mode_ids(tmp_path): ...
def test_catalog_rejects_unknown_category(tmp_path): ...
def test_get_mode_returns_none_for_unknown_id(tmp_path): ...

def test_repo_modes_yaml_is_loadable(): ...
    # 用真實 config/modes.yaml（Path(__file__).resolve().parents[2] / "config" / "modes.yaml"）
    # list_modes() 回傳 6 個 mode；red-blue 的 relay_plan steps step_id ==
    # ["blue-propose", "red-critique", "blue-revise", "judge-decide"]（相容鐵則的守門測試）
    # 且每個 relay mode 的每個 step template 對應的 prompts/{template}.md 都存在
```

**Step 3:** 跑 → FAIL（module 不存在）。

**Step 4: 實作**。先在 `runner.py` 的 `StepDefinition` 下方加：

```python
@dataclass(frozen=True)
class RelayPlan:
    steps: list[StepDefinition]
    directed_steps: dict[str, StepDefinition]
```

再寫 `backend/ai_council/meetings/modes.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ai_council.meetings.runner import RelayPlan, StepDefinition

VALID_CATEGORIES = {"relay", "parallel"}
VALID_ROLE_KINDS = {"member", "adjudicator", "synthesizer"}
VALID_INPUT_KINDS = {"text", "persona-list"}


class ModeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModeRole:
    id: str
    name: str
    color: str
    kind: str
    portrait: str | None = None


@dataclass(frozen=True)
class ModeStep:
    role: str
    template: str
    label: str


@dataclass(frozen=True)
class ModeInput:
    id: str
    label: str
    kind: str


@dataclass(frozen=True)
class ModeFanout:
    role: str
    template: str
    label: str
    min_instances: int
    max_instances: int
    instance_prompt: bool


@dataclass(frozen=True)
class ModeSynthesis:
    role: str
    template: str
    label: str


@dataclass(frozen=True)
class ModeDefinition:
    id: str
    name: str
    category: str
    tagline: str
    when_to_use: str
    sop: list[str]
    default_scene: str
    inputs: list[ModeInput]
    roles: list[ModeRole]
    steps: list[ModeStep] = field(default_factory=list)
    fanout: ModeFanout | None = None
    synthesis: ModeSynthesis | None = None

    @property
    def available(self) -> bool:
        # Only the relay executor exists today; parallel modes unlock in slice C.
        return self.category == "relay"

    def role_ids(self) -> list[str]:
        return [role.id for role in self.roles]


def relay_plan(mode: ModeDefinition) -> RelayPlan:
    if mode.category != "relay":
        raise ModeConfigError(f"Mode does not use the relay executor: {mode.id}")
    steps = [
        StepDefinition(step.template.replace("_", "-"), step.role, step.template)
        for step in mode.steps
    ]
    directed_steps = {
        step.role: StepDefinition(f"{step.role.lower()}-response", step.role, step.template)
        for step in mode.steps
    }
    return RelayPlan(steps=steps, directed_steps=directed_steps)


class ModeCatalogRepository:
    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)

    def list_modes(self) -> list[ModeDefinition]:
        if not self.config_path.exists():
            raise ModeConfigError(f"Mode config not found: {self.config_path}")
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        raw_modes = raw.get("modes", [])
        if not isinstance(raw_modes, list):
            raise ModeConfigError("modes must be a list")
        modes = [_mode_from_yaml_item(item) for item in raw_modes]
        seen: set[str] = set()
        for mode in modes:
            if mode.id in seen:
                raise ModeConfigError(f"Duplicate mode id: {mode.id}")
            seen.add(mode.id)
        return modes

    def get_mode(self, mode_id: str) -> ModeDefinition | None:
        for mode in self.list_modes():
            if mode.id == mode_id:
                return mode
        return None
```

`_mode_from_yaml_item` 解析所有欄位並驗證：id/name/category 必填、category ∈ VALID_CATEGORIES、roles 非空且 id 唯一、kind ∈ VALID_ROLE_KINDS、input kind ∈ VALID_INPUT_KINDS、relay 必有非空 steps 且每個 step.role 都在 roster、parallel 不得有 steps。錯誤一律 raise `ModeConfigError`（訊息含 mode id）。寫法比照 `models/config.py` 的 `_model_from_yaml_item`。

**Step 5:** `pytest tests/test_mode_catalog.py -q` → PASS；全套綠。

**Step 6:** `git add -A && git commit -m "feat: add mode catalog config, parser, and relay plan derivation"`

### Task 5: MeetingRunner 參數化（TDD）

**Files:**
- Modify: `backend/ai_council/meetings/runner.py`
- Test: `backend/tests/test_meeting_runner.py`

**Step 1:** 先改測試：test_meeting_runner.py 頂部加

```python
from ai_council.meetings.runner import RelayPlan, StepDefinition

RED_BLUE_PLAN = RelayPlan(
    steps=[
        StepDefinition("blue-propose", "Blue", "blue_propose"),
        StepDefinition("red-critique", "Red", "red_critique"),
        StepDefinition("blue-revise", "Blue", "blue_revise"),
        StepDefinition("judge-decide", "Judge", "judge_decide"),
    ],
    directed_steps={
        "Blue": StepDefinition("blue-response", "Blue", "blue_revise"),
        "Red": StepDefinition("red-response", "Red", "red_critique"),
        "Judge": StepDefinition("judge-response", "Judge", "judge_decide"),
    },
)
```

所有 `runner.start(...)`/`retry_failed_step(...)`/`respond_as_role(...)`/`respond_as_sequence(...)` 呼叫加 `plan=RED_BLUE_PLAN`。再加兩個新測試：

```python
COURTROOM_PLAN = RelayPlan(
    steps=[
        StepDefinition("courtroom-charge", "Prosecutor", "courtroom_charge"),
        StepDefinition("courtroom-defense", "Defense", "courtroom_defense"),
        StepDefinition("courtroom-rebuttal", "Prosecutor", "courtroom_rebuttal"),
        StepDefinition("courtroom-verdict", "Judge", "courtroom_verdict"),
    ],
    directed_steps={
        "Prosecutor": StepDefinition("prosecutor-response", "Prosecutor", "courtroom_rebuttal"),
        "Defense": StepDefinition("defense-response", "Defense", "courtroom_defense"),
        "Judge": StepDefinition("judge-response", "Judge", "courtroom_verdict"),
    },
)


def test_runner_completes_courtroom_flow(tmp_path: Path) -> None:
    # build_runner 的模板 fixture 需一併產出 courtroom_* 模板檔（見下方 Step 1 附註）
    # runner.start(..., plan=COURTROOM_PLAN, model_assignments={Prosecutor/Defense/Judge: ...})
    # 斷言 completed step_id == ["courtroom-charge", "courtroom-defense",
    #                            "courtroom-rebuttal", "courtroom-verdict"]
    # 且第二回合 start（再跑一次）產生 round-2-courtroom-charge …（round 計數跟著最後一步 courtroom-verdict 走）


def test_runner_renders_mode_inputs_into_prompt(tmp_path: Path) -> None:
    # 模板含 {{ position_a }}；runner.start(..., inputs={"position_a": "先做後端"})
    # 斷言 completed event 的 prompt_messages[0]["content"] 內含 "先做後端"
```

附註：`build_runner` 的模板產生 helper 需接受 template 名清單（預設紅藍四個），courtroom 測試傳入 courtroom 四個。

**Step 2:** 跑 → FAIL（unexpected keyword `plan`）。

**Step 3: 實作**（`runner.py`）：
- 刪除模組層 `STEPS` 與 `DIRECTED_RESPONSE_STEPS`。
- `start`/`retry_failed_step`/`respond_as_role`/`respond_as_sequence` 全部加必填 keyword 參數 `plan: RelayPlan` 與選填 `inputs: dict[str, str] | None = None`。
- 內部替換：`STEPS` → `plan.steps`；`DIRECTED_RESPONSE_STEPS.get(role)` → `plan.directed_steps.get(role)`。
- `_run_from_step`/`_run_step` 透傳 `plan`（或直接傳 `steps`）與 `inputs`；`_run_step` 呼叫 `self.prompt_renderer.render(..., inputs=inputs)`。
- `_first_incomplete_step_index(meeting_id, round_number, steps)`。
- `_next_round_number(meeting_id, plan)`：hardcoded `"judge-decide"`（line 451）→ `plan.steps[-1].step_id`。
- `retry_failed_step` 的 `next(index for ... in STEPS ...)` → 在 `plan.steps` 找；找不到（`StopIteration`）轉 raise `ValueError(f"Step is not part of this meeting's mode: {base_step_id}")`。
- `cancel`/`close` 不變。

**Step 4:** `pytest tests/test_meeting_runner.py tests/test_websocket.py -q`（websocket 測試若直接建 runner 也要補 plan）→ PASS。此時 test_api.py 會 FAIL（api.py 還沒改）——**這是預期的**，Task 6 修。若 fail 面積太大影響 commit 紀律，Task 5+6 可合併為一個 commit，但實作順序照舊。

**Step 5:** 若全套可綠則 commit：`git commit -m "refactor: parameterize relay runner with mode-derived plan"`（否則併入 Task 6 的 commit）。

### Task 6: API 接上 mode catalog（GET /modes、POST /meetings 收 mode_id/participants/inputs、各端點 mode-driven）（TDD）

**Files:**
- Modify: `backend/ai_council/api.py`
- Modify: `backend/ai_council/main.py`
- Test: `backend/tests/test_api.py`

**Step 1: failing tests**（加入 test_api.py；`create_test_app` 先改好——見 Step 3 第一點——測試才寫得動）：

```python
def test_modes_endpoint_returns_catalog(tmp_path):
    # GET /modes → 200；六個 mode；red-blue: available True、steps 帶 label；
    # brainstorm: available False、fanout.min_instances == 2

def test_create_meeting_defaults_to_red_blue(tmp_path):
    # POST /meetings {"topic": "T"}（舊 body）→ 201/200；回應 mode_id == "red-blue"
    # participants == red-blue 三角色投影（role_id/name/color/kind/model_config_id None）

def test_create_meeting_with_courtroom_mode(tmp_path):
    # body {"topic": "T", "mode_id": "courtroom"} → participants 為 Prosecutor/Defense/Judge

def test_create_meeting_rejects_unknown_mode(tmp_path):        # → 400
def test_create_meeting_rejects_parallel_mode(tmp_path):       # brainstorm → 400 "not yet supported"
def test_create_meeting_requires_debate_positions(tmp_path):
    # debate 無 inputs → 400；inputs 只有 position_a → 400；兩者齊 → 成功且回應含 inputs
def test_create_meeting_rejects_unknown_input_keys(tmp_path):  # red-blue + inputs {"x": "y"} → 400
def test_create_meeting_rejects_participant_role_not_in_mode(tmp_path):
    # courtroom + participants [{"role_id": "Blue", ...}] → 400
def test_create_meeting_stores_participant_models(tmp_path):
    # participants [{"role_id": "Prosecutor", "model_config_id": "mock-fast"}] →
    # GET /meetings/{id} 的 participants 中 Prosecutor.model_config_id == "mock-fast"

def test_legacy_meeting_projects_red_blue_participants(tmp_path):
    # 直接寫一份不含 mode_id 的 metadata.json（模擬既有資料）→
    # GET /meetings/{id} mode_id == "red-blue"、participants 三角色

def test_start_courtroom_meeting_runs_courtroom_steps(tmp_path):
    # 建 courtroom meeting → POST start {models: {Prosecutor/Defense/Judge: mock-fast}}
    # → wait_for_activity "completed" → events step_id 序列 == courtroom 四步
def test_start_rejects_missing_roles_for_mode(tmp_path):
    # courtroom + models 只給 Judge → 400 訊息列出 "Defense, Prosecutor"

def test_debate_inputs_reach_prompts(tmp_path):
    # debate meeting（position_a/b 給定）→ start → 任一 completed event 的
    # prompt_messages content 含 position_a 文字（create_test_app 的 debate 模板要含 {{ position_a }}）

def test_respond_as_role_accepts_mode_roles(tmp_path):
    # courtroom meeting → POST /roles/Prosecutor/respond → step_id "directed-1-prosecutor-response"
    # POST /roles/Blue/respond（courtroom 沒 Blue）→ 400
```

**Step 2:** 跑 → FAIL。

**Step 3: 實作**（api.py）：

1. `create_test_app` 與 `create_app` 都加 `modes_config_path` 參數。`create_test_app`：把**真實** `config/modes.yaml` 複製進 tmp（`shutil.copy(PROJECT_CONFIG / "modes.yaml", config_dir / "modes.yaml")`，PROJECT_CONFIG 用 `Path(__file__).resolve().parents[2] / "config"`）——測真檔避免兩套 yaml 漂移；prompt 模板清單擴為全部 13 個 relay 模板（4 紅藍 + 4 courtroom + 5 debate），debate 模板內容多加 ` {{ position_a }} {{ position_b }}`（僅 debate 五檔）。注意：既有 hash 斷言測試只碰紅藍模板，內容別動。
2. `main.py`：`modes_config_path=Path(os.environ.get("AI_COUNCIL_MODES_CONFIG_PATH", PROJECT_ROOT / "config" / "modes.yaml"))`。
3. imports：`from ai_council.meetings.modes import ModeCatalogRepository, ModeConfigError, ModeDefinition, relay_plan`。
4. `create_app` 內：`mode_catalog = ModeCatalogRepository(modes_config_path)`。
5. Request models：

```python
class MeetingParticipantRequest(BaseModel):
    role_id: str
    model_config_id: str | None = None
    display_name: str | None = None
    instance_prompt: str | None = None


class CreateMeetingRequest(BaseModel):
    topic: str
    mode_id: str = "red-blue"
    participants: list[MeetingParticipantRequest] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict)
```

6. helper：

```python
def get_mode_or_400(catalog: ModeCatalogRepository, mode_id: str) -> ModeDefinition:
    try:
        mode = catalog.get_mode(mode_id)
    except ModeConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    if mode is None:
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode_id}")
    return mode


def meeting_mode(catalog: ModeCatalogRepository, metadata: dict[str, Any]) -> ModeDefinition:
    return get_mode_or_400(catalog, str(metadata.get("mode_id", "red-blue")))
```

7. `GET /modes`：

```python
@app.get("/modes")
def list_modes_catalog() -> list[dict[str, Any]]:
    try:
        modes = mode_catalog.list_modes()
    except ModeConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return [project_mode(mode) for mode in modes]
```

`project_mode` 輸出完整 §16.2 結構（snake_case）＋ `available`；steps 帶 label；fanout/synthesis 有才輸出。

8. `POST /meetings` 驗證順序：mode 存在 → `mode.available`（否則 400 `f"Mode is not yet supported: {mode.id}"`）→ participants（role_id ∈ roster、不重複、model_config_id 有給就 `get_model` 驗證存在）→ inputs（key ⊆ 宣告的 input ids，否則 400；每個 `kind: text` 的 input 必須存在且 `.strip()` 非空，否則 400 `f"Missing required input: {input.id}"`）。metadata 增存 `"mode_id"`、`"participants"`（`[p.model_dump() for p in request.participants]`）、`"inputs"`。
9. `project_meeting_summary` 加參數 `mode: ModeDefinition`，輸出加：

```python
        "mode_id": mode.id,
        "participants": project_participants(mode, metadata),
```

```python
def project_participants(mode: ModeDefinition, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    stored = {
        str(item.get("role_id")): item
        for item in (metadata.get("participants") or [])
        if isinstance(item, dict)
    }
    projected = []
    for role in mode.roles:
        entry = stored.get(role.id, {})
        projected.append(
            {
                "role_id": role.id,
                "name": role.name,
                "color": role.color,
                "kind": role.kind,
                "portrait": role.portrait,
                "model_config_id": entry.get("model_config_id"),
                "display_name": entry.get("display_name") or role.name,
                "instance_prompt": entry.get("instance_prompt"),
            }
        )
    return projected
```

所有呼叫 `project_meeting_summary` 的位置（create/list/get/tags/pinned）先 `mode = meeting_mode(mode_catalog, metadata)` 再傳入。
10. `/start`：`missing_roles = sorted(set(mode.role_ids()) - request.models.keys())`；`runner.start(..., plan=relay_plan(mode), inputs=metadata.get("inputs") or {})`。`/roles/{role}/respond`、`/sequences`、`/steps/{step_id}/retry` 同樣解析 mode → plan/inputs 傳給 runner。
11. `GET /meetings/{id}` 回應同時保留 `events`（既有行為）。

**Step 4:** `pytest tests/ -q` → 全綠。

**Step 5:** `git add -A && git commit -m "feat: mode-driven meetings API with GET /modes and courtroom/debate support"`

## Phase 2 — Frontend

### Task 7: api.ts — getModes、createMeeting 帶 mode/inputs、Meeting 型別擴充

**Files:** Modify `frontend/src/api.ts`

- `Meeting` 型別加 `mode_id: string` 與 `participants: MeetingParticipant[]`（`MeetingParticipant = { role_id: string; name: string; color: string; kind: string; portrait: string | null; model_config_id: string | null; display_name: string; instance_prompt: string | null }`）。
- 新增後端 wire 型別 `BackendModeDefinition`（snake_case，含 `available`、steps 帶 `label`、`fanout`/`synthesis` optional）與 `export async function getModes(): Promise<BackendModeDefinition[]> { return getJson('/modes') }`。
- `createMeeting(topic: string, options?: { modeId?: string; inputs?: Record<string, string> })` → body `{ topic, mode_id: options?.modeId ?? 'red-blue', inputs: options?.inputs ?? {} }`。

**驗證：** `npm run build`（vue-tsc）通過。**Commit:** `feat: frontend api client for modes and mode-aware meeting creation`

### Task 8: modes.ts — 後端 catalog 為主、本地常數轉 fallback

**Files:** Modify `frontend/src/modes.ts`

依該檔頭註釋既定設計：exports 不變，資料來源可切換。

- `modeCatalog` 從 `const ...[] = [...]` 改為 `reactive<ModeDefinition[]>([redBlueMode, ...])`（初始值 = 既有六個本地常數，即 fallback）。
- 各 mode 常數（redBlueMode…）保留為 fallback 資料，`available` 維持現值（red-blue true、其餘 false）——**後端不可達時行為 == slice A**。
- 新增 `mapBackendMode(raw: BackendModeDefinition): ModeDefinition`（snake→camel：`when_to_use`→`whenToUse`、`default_scene`→`defaultScene`、fanout `min_instances`→`minInstances` 等；steps/fanout/synthesis 的 `label` 直接對應；`available` 用後端值）。
- 新增 `export async function refreshModeCatalog(): Promise<void>`：`getModes()` 成功 → `modeCatalog.splice(0, modeCatalog.length, ...fetched.map(mapBackendMode))`；失敗（catch）→ 保留 fallback，`console.warn` 即可。
- `getModeById`/`allKnownRoleIds`/`ringSeatLayout` 不需改（讀同一個陣列）。
- 更新檔頭註釋：本地常數現在是 fallback，主資料源是 GET /modes。

**驗證：** `npm run build` 通過。**Commit:** `feat: mode catalog fetches from GET /modes with local fallback`

### Task 9: useCouncil.ts — active mode 跟著選中的 meeting 走

這是前端最大的一步。現況：`activeMode`/`activeModeRoles`/`councilRoles` 是模組層常數（useCouncil.ts:55-74），`roleIcon`/`roleClass`/`roleColor`/`roleColorVars` 等模組層函式讀它們；`FIXED_ROUND_STEP_ROLES`/`FIXED_ROUND_BASE_STEPS`（:82-93）手寫紅藍步驟。

**Files:** Modify `frontend/src/composables/useCouncil.ts` + 所有 import 這些符號的元件（`grep -rn "activeMode\|councilRoles\|activeModeRoles" frontend/src` 逐一確認：至少 ActionBar.vue、CouncilStage.vue、SettingsModal.vue、RoleDrawer.vue）。

**設計（讓模組層 helper 函式簽名不變）：**

```ts
// 模組層：目前作用中的 mode，預設 red-blue。由 useCouncil() 在 selectedMeeting 變化時同步。
// 用 computed 包 ref，讓既有 `import { activeMode }` 的元件在 template 中自動解包。
const activeModeSource = ref<ModeDefinition>(getModeById(DEFAULT_MODE_ID)!)
export const activeMode = computed(() => activeModeSource.value)
export const activeModeRoles = computed(() => activeModeSource.value.roles)
export const councilRoles = computed(() => activeModeSource.value.roles.map((r) => r.id))
```

- 所有模組層函式（`activeRoleDefinition`/`isCouncilRole`/`roleIcon`/`roleClass`/`roleColor`/`roleColorVars`）改讀 `activeModeSource.value`；對外簽名不變。
- `useCouncil()` 內加 `watch(selectedMeeting, ...)`：`activeModeSource.value = getModeById(selectedMeeting.value?.mode_id ?? DEFAULT_MODE_ID) ?? getModeById(DEFAULT_MODE_ID)!`。
- `initialize()`（或既有的啟動載入函式）開頭 `await refreshModeCatalog()`（失敗不擋啟動——refreshModeCatalog 內已 catch）。
- `selectedModels`/`modelTestResults`：由固定初始化改為「watch activeMode，為 roster 補齊 key」：

```ts
watch(councilRoles, (roles) => {
  const first = models.value[0]?.id ?? ''
  selectedModels.value = Object.fromEntries(
    roles.map((role) => [role, selectedModels.value[role] || first]),
  )
  // modelTestResults 同樣補齊（新 key 給 unknown 初始值）
}, { immediate: true })
```

- `sequencePresets`：從硬編四組改為 computed 推導（對 red-blue 產出與現值完全相同的四組——members=[Blue,Red]、adjudicator=Judge）：

```ts
export const sequencePresets = computed<SequencePreset[]>(() => {
  const mode = activeModeSource.value
  const members = mode.roles.filter((r) => r.kind === 'member').map((r) => r.id)
  const adjudicator = mode.roles.find((r) => r.kind !== 'member')?.id
  if (!adjudicator || members.length < 2) return []
  const reversed = [...members].reverse()
  const label = (roles: string[]) => roles.join(' -> ')
  return [
    { id: 'members-reversed-adj', label: label([...reversed, adjudicator]), roles: [...reversed, adjudicator] },
    { id: 'members-adj', label: label([...members, adjudicator]), roles: [...members, adjudicator] },
    { id: 'members-reversed', label: label(reversed), roles: reversed },
    { id: 'adj-only', label: `${adjudicator} only`, roles: [adjudicator] },
  ]
})
```

（e2e 若斷言 preset 的 id/label 需同步更新——先 grep `tests/e2e` 的 `sequence`。）
- `FIXED_ROUND_STEP_ROLES`/`FIXED_ROUND_BASE_STEPS` 刪除，改為由 activeMode.steps 推導（原註釋說「後端不變所以手寫」——slice B 後端已 mode-driven，該理由失效）：

```ts
const roundBaseSteps = computed(() =>
  activeModeSource.value.steps?.map((s) => s.template.replace(/_/g, '-')) ?? [],
)
function retryCascadeRoles(baseStepId: string): CouncilRole[] {
  const steps = activeModeSource.value.steps ?? []
  const index = roundBaseSteps.value.indexOf(baseStepId)
  if (index < 0) return []
  return steps.slice(index).map((s) => s.role)
}
```

原本讀 `FIXED_ROUND_STEP_ROLES[...]` 的地方改呼叫 `retryCascadeRoles(...)`；讀 `FIXED_ROUND_BASE_STEPS` 的地方改 `roundBaseSteps.value`。
- `createNewMeeting` 加參數 `(modeId: string, inputs: Record<string, string>)` → `createMeeting(topic.value, { modeId, inputs })`。
- 元件端：import 的 `activeMode`/`councilRoles` 在 `<script>` 內取值處加 `.value`（template 內自動解包不用改）。逐一編譯錯誤驅動修完。

**驗證：** `npm run build` 通過。**Commit:** `feat: drive active mode from the selected meeting`

### Task 10: NewCaseModal — courtroom/debate 可建立 + 辯論雙立場輸入

**Files:** Modify `frontend/src/components/NewCaseModal.vue`（必要時 `ModeCard.vue`——它已依 `mode.available` 顯示「即將推出」，catalog 換資料源後自動生效，應不需改）。

- `chooseMode` 邏輯不變（`available` 現在來自後端：relay 三模式 true、parallel false）。
- participants step 增加 mode inputs 表單：`selectedMode.inputs` 中 `kind === 'text'` 的每一項渲染一個 `<input v-model="inputValues[input.id]" :data-testid="`mode-input-${input.id}`" :aria-label="input.label" />`（`persona-list` 本切片不會出現在可建立模式，忽略）。
- `const inputValues = ref<Record<string, string>>({})`；換模式或重開 modal 時清空。
- 建立按鈕 disabled 條件追加：所有 text inputs `.trim()` 非空。
- `submit()` → `createNewMeeting(selectedMode.value.id, { ...inputValues.value })`。
- 模式選擇提示文字「目前僅『紅藍對抗』可實際建立」改為由資料驅動的中性文案（例：「灰階卡片為即將推出的模式」）。

**驗證：** `npm run build`。**Commit:** `feat: create courtroom and debate meetings from the mode picker`

### Task 11: 選中會議時自動套用 mode 的 default_scene（非持久覆蓋）

**Files:** Modify `frontend/src/scenes.ts`、`frontend/src/composables/useCouncil.ts`

- scenes.ts：加 `const sceneOverrideId = ref<string | null>(null)`；`currentScene` 改為先找 override 再找 selectedSceneId；`setScene`（使用者手選）先 `sceneOverrideId.value = null` 再照舊持久化；新增 `export function applyModeScene(sceneId: string | null) { sceneOverrideId.value = sceneId && scenes.some((s) => s.id === sceneId) ? sceneId : null }`。
- useCouncil.ts 的 `watch(selectedMeeting)`（Task 9 加的那個）內：選中 meeting → `applyModeScene(mode.defaultScene)`；無選中 → `applyModeScene(null)`。效果：開 courtroom 會議自動進法院場景，使用者仍可在 Settings 手動改（手動改優先且持久）。

**驗證：** `npm run build`。**Commit:** `feat: apply mode default scene when opening a meeting`

### Task 12: e2e 更新 + 新增 courtroom/debate 流程測試

**Files:** Modify `frontend/tests/e2e/control-flow.spec.ts`

先讀 `playwright.config.ts` 確認 e2e 如何起後端（若起真後端，GET /modes 會回真 catalog：red-blue/courtroom/debate available）。

- 更新 line 791 測試：「只有 red-blue 可建立」→「red-blue/courtroom/debate 可建立（選擇按鈕 enabled），三個 parallel 模式仍『即將推出』disabled」。
- 更新開頭 helper（line 9-12）若它假設只有 red-blue 有活按鈕。
- 新增測試 A（courtroom happy path）：New Case → 選 courtroom → 建立 → Settings 為 Prosecutor/Defense/Judge 指派 mock 模型（model select 的 data-testid 是由 role 派生的 `blue-model-select` 形式 → courtroom 應為 `prosecutor-model-select` 等；先確認 SettingsModal 的 testid 生成方式，若是硬編需在 Task 9 改為 role 派生）→ 開始審議 → 等待四步完成 → 斷言舞台上出現檢察官/辯護律師/法官席位、事件流含「檢察官指控」等步驟。
- 新增測試 B（debate inputs）：選 debate → 立場欄空時建立鈕 disabled → 填 position_a/b → 建立成功。
- 跑 `npm run test:e2e` 全綠（含既有 900+ 行案例）。

**Commit:** `test: e2e coverage for courtroom and debate modes`

## Phase 3 — 收尾

### Task 13: 全面驗證 + 文件

1. `cd backend && .venv/bin/python -m pytest tests/ -q` 全綠。
2. `cd frontend && npm run build && npm run test:e2e` 全綠。
3. 手動冒煙（REQUIRED SUB-SKILL: superpowers:verification-before-completion）：起後端 + 前端 dev server，用 mock 模型建一場 courtroom 與一場 debate 跑完整回合；確認舊資料（`data/meetings/` 現有會議）開起來仍是紅藍三席、無 console 錯誤。
4. spec.md §16.7 slice B 條目補記「已完成（日期）」；若 `.env.example` 存在，補 `AI_COUNCIL_MODES_CONFIG_PATH`。
5. Commit 殘餘變更。

### Task 14: Code review + merge

1. REQUIRED SUB-SKILL: superpowers:requesting-code-review（或 code-review skill）審 `main..mode-system-slice-b`。
2. 修正 review 發現的問題。
3. 依 superpowers:finishing-a-development-branch：merge 回 main、刪 worktree 與 branch（使用者政策：每個 feature 立即 merge + 清理，不批次）。
