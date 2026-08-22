---
title: "Protokflow - Token-Driven UI Prototyping Core & Dual Protocol Adapters - Plan"
type: feat
date: 2026-08-22
topic: protokflow-hybrid-core
artifact_contract: ce-unified-plan/v1
artifact_readiness: requirements-only
product_contract_source: ce-brainstorm
execution: code
---

# Protokflow - Token-Driven UI Prototyping Core & Dual Protocol Adapters - Plan

## Goal Capsule

### Objective
AI 코딩 에이전트(Claude Desktop, Cursor, Codex 등)와 인간 엔지니어가 단 1회의 도구 호출로 3계층 디자인 토큰 기반 UI 후보군을 생성하고, 로컬 브라우저에서 초저지연(<16ms) 핫리로드로 나란히 비교·수정하며, 무오류 React/Tailwind 프로덕션 코드로 즉시 내보낼 수 있는 독립형 프로토타이핑 엔진을 구축한다.

### Means
전송 프로토콜과 독립된 순수 Python 3계층 토큰 엔진(`protokflow.core`)을 구축하고, 상위에 MCP stdio 도구 어댑터(`protokflow.adapters.mcp`)와 Starlette/FastAPI ASGI 웹 프리뷰 어댑터(`protokflow.adapters.http`)를 분리 제공하는 하이브리드 코어 아키텍처.

### Product Authority
이 계획서는 `protokflow`의 코어 토큰 해석 엔진, MCP 및 HTTP 듀얼 어댑터 인터페이스, 브라우저 실시간 프리뷰 쉘, React/Tailwind 코드 추출 사양을 규정한다. 외부 클라우드 디자인 툴 실시간 양방향 동기화나 백엔드 데이터 목킹은 범위 외로 정의한다.

### Open Blockers
None.

---

## Product Contract

### Summary
Protokflow는 Meta Astryx 기반의 3계층 디자인 토큰(Foundations → Components → Patterns)을 정적 HTML/CSS로 컴파일하는 순수 Python 코어 엔진(`protokflow.core`)과, 에이전트용 MCP 도구 어댑터 및 브라우저용 ASGI 프리뷰 서버를 얇은 래퍼로 제공하는 하이브리드 UI 프로토타이핑 툴킷이다. 에이전트에게는 `uvx protokflow mcp`를 통한 제로 컨피그 도구 호출을, 사용자에게는 CSS 변수 웹소켓 패치를 통한 16ms 이내 초저지연 실시간 핫리로드 비교 환경을 제공한다.

### Problem Frame
기존의 로컬 레포지토리 종속형 디자인 하니스(`design-harness`)는 단일 화면 후보를 생성하기 위해 20회 이상의 세부 CLI 호출과 엄격한 SHA-256 해시 추적, 임대(lease) 관리 등 지나치게 많은 트랜잭션 의례를 요구했다. 이로 인해 AI 코딩 에이전트가 화면 프로토타입을 빠르게 생성·탐색·비교하는 과정에서 심각한 병목과 파싱 에러를 겪었다. 또한 전송 계층 선택 시 "순수 MCP"는 웹 프리뷰 백그라운드 프로세스 및 포트 충돌 관리에 취약하고, "순수 FastAPI"는 에이전트의 직접 도구 호출에 불필요한 HTTP 통신 의례를 요구하는 문제가 있었다.

### Key Decisions
- **KD1 (Headless Domain Engine Core with Dual Adapters)**: 3계층 토큰 해석과 Jinja2 렌더링을 순수 Python 라이브러리로 분리하고, 상위에 MCP 어댑터와 ASGI 웹 어댑터를 얇은 래퍼로 얹는다. `(session-settled: user-directed — chosen over single-protocol lock-in: eliminates false dichotomy and enables 100% testable core without network mocks)` `Governs R1, R2, R3, R4, R7, R13`
- **KD2 (In-Process FastMCP / Embedded ASGI Preview with Process Tethering)**: MCP stdio 실행 시 백그라운드에서 동적 임시 포트(`port=0`) 루프백 ASGI 서버를 구동하며, 에이전트 stdio EOF 감지 시 500ms 이내에 자동 정리(Dead-Man's Switch)한다. `(session-settled: user-approved — chosen over static fixed-port daemon: eliminates port 4100 collisions and zombie Uvicorn leaks)` `Governs R8, R9`
- **KD3 (Zero-Compile CSS Custom Property Injection for <16ms Hot-Reload)**: Astryx 토큰을 브라우저 CSS 변수로 매핑하고, `patch_tokens` 호출 시 웹소켓으로 토큰 델타를 주입하여 전체 HTML 재렌더링 없이 스타일을 즉시 모핑한다. `(session-settled: user-approved — chosen over full HTML re-render: guarantees sub-16ms latency and preserves input focus/scroll)` `Governs R10`
- **KD4 (Single-Source Pydantic v2 Schemas for MCP Tools & OpenAPI Specs)**: 토큰 계층 및 5종 도구 인터페이스를 Pydantic v2 모델로 정의하여 MCP JSONSchema와 FastAPI Swagger 문서를 자동 생성한다. `(session-settled: user-approved — chosen over duplicated schema definitions: prevents schema drift)` `Governs R5, R12`
- **KD5 (Deterministic AST-Free Template Swizzle Exporter)**: `export_prototype`은 사전 검증된 컴포넌트 템플릿에 토큰을 1:1 치환하는 스위즐(swizzle) 방식으로 100% 문법 무결한 React/Tailwind 코드를 방출한다. `Governs R14, R15`

### Actors
- **A1 (AI Coding Agent)**: Claude Desktop, Cursor, Codex 등 MCP 프로토콜을 통해 `create_prototype_run`, `patch_tokens`, `export_prototype` 도구를 직접 호출하는 주체.
- **A2 (Human Product Engineer / Designer)**: 에이전트와 대화하며 로컬 브라우저에서 생성된 다중 UI 후보군을 실시간 비교하고 피드백을 제공하는 최종 사용자.

### Requirements

#### Core Token Resolution & Jinja2 Engine (`protokflow.core`)
- R1. Astryx 3계층 디자인 토큰 체계(`Foundations → Components → Patterns`)를 지원하고 토큰 캐스케이드 참조(`{colors.indigo-600}`, `{radii.md}`)를 결정론적으로 해석해야 한다.
- R2. 표준 UI 레이아웃 프리셋(`split-card`, `centered-modal`, `dashboard-shell`, `form-view` 등)을 내장하고 Jinja2 기반으로 1ms 이내 무오류(Zero-syntax-error) HTML을 렌더링해야 한다.
- R3. 모든 코어 엔진 로직은 네트워크나 I/O 전송 계층 의존성 없이 순수 Python 함수 및 Pydantic 모델로 동작해야 한다.

#### MCP Protocol Adapter (`protokflow.adapters.mcp`)
- R4. Python 공식 `mcp` SDK 기반 stdio 및 SSE 전송 모드를 지원하며, `uvx protokflow mcp` 단일 명령으로 무설치 즉시 실행되어야 한다.
- R5. 핵심 MCP Tool Surface 5종(`create_prototype_run`, `patch_tokens`, `update_slot_custom`, `serve_preview`, `export_prototype`)을 표준 JSONSchema로 노출해야 한다.
- R6. `create_prototype_run` 및 `patch_tokens` 호출 시 텍스트 URL과 함께 표준 MCP `ImageContent`(Base64 스냅샷 이미지) 옵션을 지원해야 한다.

#### ASGI Web Preview Adapter (`protokflow.adapters.http`)
- R7. Starlette/Uvicorn 기반의 초경량 ASGI 서버를 내장하여 브라우저 프리뷰 및 WebSocket 핫리로드를 제공해야 한다.
- R8. 고정 포트(4100) 충돌을 방지하기 위해 동적 임시 포트(port 0) 자동 바인딩 및 PID/포트 락파일(`.protokflow/daemon.json`)을 지원해야 한다.
- R9. MCP stdio 프로세스 종료 시 stdio 파이프의 EOF를 감지하여 백그라운드 프리뷰 서버를 500ms 이내에 자동 정리(Dead-Man's Switch)해야 한다.

#### Live Preview & Hot-Reload UX
- R10. Astryx Foundations 및 Components 토큰을 브라우저 `:root`의 CSS Custom Properties로 매핑하고, `patch_tokens` 호출 시 WebSocket으로 토큰 델타를 전송하여 `style.setProperty`로 16ms 이내 즉각 화면 스타일을 모핑해야 한다.
- R11. 다중 후보군(`c1`, `c2`) 및 컴포넌트 상태를 나란히 비교할 수 있는 동기화 뷰포트 매트릭스(Synchronized Viewport Matrix) 뷰를 브라우저에 제공해야 한다.

#### Schema Parity & Code Export
- R12. 3계층 디자인 토큰과 도구 인터페이스를 Pydantic v2 단일 소스로 정의하여 MCP Tool JSONSchema와 FastAPI OpenAPI 문서를 스키마 드리프트 없이 자동 동기화해야 한다.
- R13. `protokflow serve` CLI 명령을 통해 개발자 및 테스터가 직접 브라우저에서 대화형 Swagger API 및 템플릿 플레이그라운드를 사용할 수 있어야 한다.
- R14. `export_prototype` 호출 시 확정된 후보의 스펙을 검증된 템플릿 기반 스위즐(swizzle) 방식으로 100% 문법 오류 없는 React JSX/TSX 컴포넌트 및 Tailwind CSS 클래스로 내보내야 한다.
- R15. `export_prototype`의 포맷으로 `react-tailwind`, `vue-tailwind`, `html-css`, `json-tokens`를 지원해야 한다.

### Key Flows

#### F1: Initial Exploration Flow (Single-Turn Batch Generation)
- **Trigger**: 에이전트가 사용자의 UI 요구사항을 수신.
- **Path**:
  1. 에이전트가 `create_prototype_run` MCP 도구를 호출하며 목표와 변량 축(variation axes) 토큰을 전달.
  2. 코어 엔진이 토큰 캐스케이드를 해석하고 Jinja2 프리셋 템플릿으로 후보군 HTML을 렌더링 (<1ms).
  3. 어댑터가 동적 루프백 ASGI 서버를 바인딩하고 접속 URL 및 선택적 스크린샷 이미지를 반환.
- **Covers**: R1, R2, R4, R5, R6, R8.

#### F2: Live Visual Feedback & Hot-Reload Loop
- **Trigger**: 사용자가 브라우저 프리뷰를 확인하고 토큰 수정을 요청.
- **Path**:
  1. 에이전트가 `patch_tokens` MCP 도구를 호출하여 특정 후보의 토큰 패치 전달.
  2. ASGI 서버가 WebSocket을 통해 대상 후보의 브라우저 뷰포트에 토큰 델타를 브로드캐스트.
  3. 브라우저가 CSS Custom Properties를 16ms 이내에 갱신하여 화면 새로고침 없이 즉시 반응.
- **Covers**: R5, R7, R10, R11.

#### F3: Final Selection & Swizzle Code Export Flow
- **Trigger**: 사용자가 최종 후보를 확정하고 코드 반영을 요청.
- **Path**:
  1. 에이전트가 `export_prototype` MCP 도구를 호출 (`format: "react-tailwind"`).
  2. 코어 스위즐 엔진이 컴포넌트 템플릿에 최종 토큰을 주입하여 독립형 TSX 및 Tailwind 코드를 반환.
  3. 에이전트가 생성된 코드를 프로젝트 레포지토리 파일 시스템에 기록.
- **Covers**: R5, R14, R15.

### Acceptance Examples

#### AE1: Single-Turn Candidate Generation via MCP
- **Given**: 에이전트가 `protokflow` MCP 서버에 연결되어 있음.
- **When**: 에이전트가 `create_prototype_run`을 `layout_preset: "split-card"`, 2개 후보(`c1`, `c2`)로 호출.
- **Then**: 서버는 50ms 이내에 `run_id`와 `http://localhost:<dynamic_port>/preview?run_id=...` 접속 URL을 반환하고 브라우저에서 두 화면이 나란히 렌더링됨.
- **Covers**: R1, R2, R4, R5, R8, R11.

#### AE2: Sub-16ms Token Patch via WebSocket without Focus Loss
- **Given**: 사용자가 브라우저 프리뷰 화면의 인풋 폼에 텍스트를 입력 중인 상태.
- **When**: 에이전트가 `patch_tokens`를 호출하여 `components.primary-button.radius: "16px"`를 전달.
- **Then**: 브라우저의 버튼 곡률이 즉각 변경되며, 입력 폼 텍스트나 커서 포커스 유실, 스크롤 튐이 발생하지 않음.
- **Covers**: R7, R10.

#### AE3: Automatic Daemon Teardown on Stdio Disconnect
- **Given**: Claude Desktop 또는 Cursor에서 `uvx protokflow mcp`로 프리뷰 서버가 동작 중임.
- **When**: 사용자가 IDE를 닫거나 에이전트 프로세스가 종료됨.
- **Then**: stdio 파이프의 EOF를 감지하여 백그라운드 ASGI 서버 프로세스가 500ms 이내에 안전하게 종료되고 포트가 즉시 반환됨.
- **Covers**: R8, R9.

#### AE4: Zero-Drift Standalone HTTP Swagger Inspection
- **Given**: 개발자가 터미널에서 `protokflow serve` 명령을 실행함.
- **When**: 브라우저에서 `http://localhost:4100/docs`에 접속.
- **Then**: MCP 도구와 100% 동일한 Pydantic v2 스키마 기반의 인터랙티브 Swagger UI가 표시되며 REST 및 WebSocket API 테스트가 가능함.
- **Covers**: R3, R12, R13.

### Scope Boundaries

#### In-Scope
- 순수 Python 기반 전송 독립형 3계층 토큰 해석 엔진 (`protokflow.core`).
- 공식 Python SDK 기반 표준 MCP stdio/SSE 도구 어댑터 5종 (`protokflow.adapters.mcp`).
- Starlette/Uvicorn 기반 경량 ASGI 프리뷰 서버 및 동적 포트/수명주기 연동 (`protokflow.adapters.http`).
- WebSocket 기반 CSS Custom Property 마이크로 패치 (<16ms) 및 다중 뷰포트 매트릭스 UI.
- Pydantic v2 단일 소스 기반 MCP JSONSchema 및 OpenAPI 스펙 자동 동기화.
- 템플릿 스위즐 방식의 React/Tailwind 및 Vue 코드 추출 (`export_prototype`).

#### Deferred for Later
- 비주얼 웹 인스펙터의 슬라이더 조작을 클립보드 프롬프트로 역변환하는 브리지 도구.
- 기업 커스텀 디자인 시스템용 프로젝트별 로컬 템플릿 오버라이드 레지스트리 (`.protokflow/presets/`).
- 4개 이상 다중 후보군 렌더링 시 가상화 캔버스 최적화.

#### Outside Product Identity
- Figma, Adobe XD 등 클라우드 디자인 툴과의 실시간 양방향 동기화.
- 백엔드 REST/GraphQL API 호출 데이터 목킹 엔진.
- Git DAG 기반의 복잡한 3-Way Rebase 트랜잭션 관리 체계.

### Success Criteria
- **SC1 (단순성)**: 에이전트가 단 1회의 MCP 도구 호출로 2개 이상의 브라우저 후보 화면을 즉시 띄울 수 있어야 함.
- **SC2 (무결성)**: Jinja2 템플릿 토큰 주입 및 React 컴포넌트 코드 추출 시 문법/파싱 에러가 0건이어야 함.
- **SC3 (반응성)**: `patch_tokens` 호출 시 브라우저 CSS 변수 핫리로드 반응 속도가 16ms 이내여야 함.
- **SC4 (배포성)**: `uvx protokflow mcp` 명령 하나로 Claude Desktop, Codex, Cursor 등 주요 에이전트 환경에서 즉시 연동 가능해야 함.
- **SC5 (격리성)**: 코어 비즈니스 로직 단위 테스트가 네트워크 목킹 없이 10ms 이내에 통과해야 함.
