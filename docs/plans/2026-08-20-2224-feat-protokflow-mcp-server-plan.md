---
title: "feat: Protokflow - Token-Driven UI Prototyping MCP Server (Python)"
type: feat
status: proposed
date: 2026-08-20
artifact_contract: ce-unified-plan/v1
artifact_readiness: requirements-only
product_contract_source: ce-brainstorm
---

# feat: Protokflow - Token-Driven UI Prototyping MCP Server (Python)

## Goal Capsule

### Problem Statement
기존의 로컬 레포지토리 종속형 디자인 하니스(`design-harness`)는 특정 프론트엔드 프로젝트에 강하게 결합되어 있으며, 단일 화면 후보를 생성하기 위해 20회 이상의 세부 CLI 호출과 엄격한 SHA-256 해시 추적, 임대(lease) 관리 등 지나치게 많은 트랜잭션 의례(ceremony)를 요구한다. 이로 인해 AI 코딩 에이전트가 화면 프로토타입을 빠르게 생성·탐색·비교하는 과정에서 심각한 병목과 파싱 에러를 겪고 있다.

### Desired Outcome
모든 프론트엔드 프로젝트(React, Vue, Svelte, HTML/CSS 등)에서 AI 코딩 에이전트가 단 1~2회의 도구 호출로 디자인 토큰 기반의 다양한 UI 후보군을 생성하고, 로컬 브라우저에서 나란히 비교하며, 선택적 커스터마이징을 거쳐 실제 프로젝트 코드로 내보낼 수 있는 독립형 **Python 기반 MCP(Model Context Protocol) 서버 프로젝트 `Protokflow`**를 구축한다.

### Target Users / Actors
- **Primary Actor**: Claude Desktop, Codex, Cursor 등 MCP 프로토콜을 지원하는 AI 코딩 에이전트
- **End User**: 에이전트와 대화하며 브라우저에서 실시간으로 UI 후보를 비교·선택하고 피드백을 전달하는 제품 엔지니어 및 디자이너

---

## Product Contract

### 1. Scope Boundaries

#### In-Scope
- **Python 기반 독립형 MCP 서버 아키텍처**:
  - Python 공식 `mcp` SDK 기반 표준 MCP 서버 구현 (stdio 및 SSE 전송 모드 지원).
  - `uv` / `uvx` 또는 `pipx`를 통한 무설치 원라인 실행 (`uvx protokflow`).
- **핵심 MCP Tool Surface (5종)**:
  1. `create_prototype_run`: 화면 목표, 참조 이미지/스펙, 레이아웃 프리셋, 변량 축(variation axes) 및 디자인 토큰을 받아 후보 화면들을 일괄 생성하고 프리뷰 세션을 초기화.
  2. `patch_tokens`: 특정 후보의 디자인 토큰(색상, 비율, 타이포그래피, 텍스트)을 부분 수정하여 브라우저에 즉각 반영.
  3. `update_slot_custom`: 템플릿 표준 토큰 외에 커스텀 HTML/CSS 조각을 특정 영역에 직접 주입.
  4. `serve_preview`: 생성된 후보 화면 및 상태(Default, Loading, Error 등)를 비교·확인할 수 있는 로컬 웹 프리뷰 서버 실행 및 URL 반환.
  5. `export_prototype`: 사용자가 채택한 후보의 스펙(Tailwind CSS 매핑, React JSX 컴포넌트 구조, 토큰 정의)을 프론트엔드 코드로 내보내기.
- **토큰 기반 Jinja2 템플릿 렌더링 엔진**:
  - 표준 UI 레이아웃 프리셋 내장 (Split Card, Centered Modal, Dashboard Shell, Form Table 등).
  - Jinja2 기반 토큰 주입을 통한 무오류(Zero-syntax-error) 정적 HTML/CSS 고속 생성 (<1ms).
- **Starlette / Uvicorn 기반 실시간 브라우저 프리뷰**:
  - WebSocket 기반 핫리로드(Hot-Reload): 토큰 수정 시 브라우저 새로고침 없이 즉각 화면 반응.
  - 다중 후보 및 상태별 나란히 비교(Side-by-Side Comparison) 뷰 제공.

#### Out-of-Scope
- Figma, Adobe XD 등 외부 디자인 툴과의 실시간 클라우드 양방향 동기화 (로컬 이미지/토큰 중심).
- 백엔드 API와의 실시간 데이터 통신 목업 (순수 프론트엔드 인터페이스 탐색에 집중).
- 프로덕션 배포 파이프라인 (완성된 스펙을 로컬 코드로 내보내는 것까지만 담당).

---

### 2. Core MCP Tool Interface

```json
// 1. create_prototype_run
{
  "name": "create_prototype_run",
  "description": "화면 목표와 디자인 토큰을 받아 프로토타입 후보군을 일괄 생성하고 프리뷰를 시작합니다.",
  "parameters": {
    "screen_goal": "string",
    "image_path": "string (optional)",
    "layout_preset": "split-card | centered-modal | dashboard-shell | form-view",
    "variation_axes": ["string"],
    "candidates": [
      {
        "id": "string",
        "label": "string",
        "tokens": { "key": "value" }
      }
    ]
  }
}

// 2. patch_tokens
{
  "name": "patch_tokens",
  "description": "특정 후보의 디자인 토큰을 부분 수정하고 브라우저 프리뷰에 즉시 반영합니다.",
  "parameters": {
    "run_id": "string",
    "candidate_id": "string",
    "token_patches": { "key": "value" }
  }
}

// 3. update_slot_custom
{
  "name": "update_slot_custom",
  "description": "특정 후보 영역에 커스텀 HTML/CSS 조각을 직접 주입합니다.",
  "parameters": {
    "run_id": "string",
    "candidate_id": "string",
    "target_region": "string",
    "custom_html": "string"
  }
}

// 4. serve_preview
{
  "name": "serve_preview",
  "description": "로컬 브라우저 프리뷰 서버를 기동하고 접속 URL을 반환합니다.",
  "parameters": {
    "run_id": "string",
    "port": "number (optional, default: 4100)"
  }
}

// 5. export_prototype
{
  "name": "export_prototype",
  "description": "채택된 후보의 스펙을 React/Tailwind 컴포넌트 코드 및 토큰으로 내보냅니다.",
  "parameters": {
    "run_id": "string",
    "candidate_id": "string",
    "format": "react-tailwind | vue-tailwind | html-css | json-tokens"
  }
}
```

---

### 3. Design Token Schema Standard

Protokflow는 다음과 같은 계층형 디자인 토큰 구조를 표준으로 채택한다:

1. **`colors`**:
   - `primary`, `primary_gradient_start`, `primary_gradient_end`, `surface`, `background`, `text_main`, `text_muted`, `border`, `danger`
2. **`layout`**:
   - `card_ratio` (예: "50:50-modal", "50:50-fullscreen", "40:60-split"), `border_radius`, `padding`, `max_width`, `shadow`
3. **`typography`**:
   - `font_family`, `title_size`, `body_size`, `font_weight_bold`, `font_weight_normal`
4. **`content`**:
   - `brand_title`, `brand_slogan`, `form_title`, `submit_text`, `security_badge_text`, `field_labels`

---

### 4. Technical Architecture (Python Stack)

- **Language / Runtime**: Python 3.12+
- **MCP Framework**: `mcp` (공식 Python SDK)
- **Template Engine**: `Jinja2` (내장 프리셋 및 안전한 토큰 렌더링)
- **Web & Preview Server**: `Starlette` + `Uvicorn` + `websockets` (초경량 실시간 핫리로드)
- **Packaging & Execution**: `pyproject.toml` (Hatchling / Flit / PDM) + `uv` 지원 (`uvx protokflow`)

---

### 5. Workflow Lifecycle

1. **Initial Exploration (1 Turn)**
   - 에이전트가 사용자의 요구사항과 참조 이미지를 기반으로 `create_prototype_run`을 호출.
   - 서버가 Jinja2 템플릿으로 후보군 HTML/CSS를 자동 렌더링하고 로컬 프리뷰 서버를 기동하여 URL 반환.
2. **Live Feedback & Tuning (Optional Iterations)**
   - 사용자가 프리뷰 화면을 보고 피드백을 전달.
   - 에이전트는 `patch_tokens` 또는 `update_slot_custom`을 호출하여 특정 후보만 실시간 튜닝.
3. **Selection & Export (Final Turn)**
   - 사용자가 후보를 확정하면 `export_prototype`을 호출하여 React 컴포넌트 코드 및 Tailwind 토큰 스펙을 수신하고 실제 프로젝트에 반영.

---

### 6. Success Criteria & Verification Signals

- **단순성**: 에이전트가 단 1개의 MCP 도구 호출로 2개 이상의 브라우저 후보 화면 세트를 즉시 띄울 수 있어야 함.
- **무결성**: Jinja2 템플릿 기반 토큰 주입 시 HTML 문법 오류나 인라인 스타일 따옴표 충돌 없이 100% 정상 렌더링되어야 함.
- **반응성**: `patch_tokens` 호출 시 200ms 이내에 브라우저 프리뷰 화면에 변경사항이 핫리로드되어야 함.
- **배포성**: `uvx protokflow` 명령 하나로 Claude Desktop, Codex, Cursor 등 주요 에이전트 환경에서 즉시 연동 가능해야 함.

