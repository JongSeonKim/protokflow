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

> 관련 문서: [데이터베이스 스키마 설계](../concepts/database-schema.md) · [디자인 토큰 아키텍처](../concepts/token-3tier-architecture.md) · [MCP+HTTP 하이브리드 DB 스키마 리서치](../research/2026-08-22-mcp-http-hybrid-db-schema-research.md)

## Goal Capsule

### Objective
AI 코딩 에이전트(Claude Desktop, Cursor, Codex 등)와 인간 엔지니어가 단 1회의 도구 호출로 `DESIGN.md` 기반 다중 디자인 시스템 및 3계층 디자인 토큰 기반 UI 후보군을 생성하고, 로컬 브라우저에서 초저지연(<16ms) 핫리로드로 나란히 비교·수정하며, 탐색 결과를 파생 디자인 시스템으로 축적했다가 원본 `DESIGN.md`에 승격하고, 무오류 React/Tailwind 프로덕션 코드로 즉시 내보낼 수 있는 독립형 프로토타이핑 엔진을 구축한다.

### Means
전송 프로토콜과 독립된 순수 Python 3계층 토큰 엔진(`protokflow.core`) 및 SQLite/SQLModel 기반 `DESIGN.md` 디자인 시스템 저장소를 구축하고, 상위에 MCP stdio 도구 어댑터(`protokflow.adapters.mcp`)와 Starlette/FastAPI ASGI 웹 프리뷰 및 관리 어댑터(`protokflow.adapters.http`)를 분리 제공하는 하이브리드 코어 아키텍처.

### Product Authority
이 계획서는 `protokflow`의 코어 토큰 해석 엔진, MCP 및 HTTP 듀얼 어댑터 인터페이스, 브라우저 실시간 프리뷰 쉘, React/Tailwind 코드 추출 사양을 규정한다. 외부 클라우드 디자인 툴 실시간 양방향 동기화나 백엔드 데이터 목킹은 범위 외로 정의한다.

### Open Blockers
None.

---

## Product Contract

### Summary
Protokflow는 Google Labs의 `DESIGN.md` 표준 포맷(YAML Front Matter + Markdown)을 수용하는 다중 디자인 시스템 기반 3계층 디자인 토큰(Foundations → Components → Patterns) 런타임 엔진(`protokflow.core`)과, 에이전트용 MCP 도구 어댑터 및 브라우저용 ASGI 프리뷰/관리 서버를 제공하는 하이브리드 UI 프로토타이핑 툴킷이다. 레포지토리 단위의 격리된 SQLite DB(`.protokflow/protokflow.db`)가 디자인 시스템, 토큰, 프로토타입 세션을 관리하고 `DESIGN.md` 파일은 Git을 통한 팀 동기화 채널로 유지되며, 웹 UI(`/admin`)를 통한 편집과 에이전트 도구 호출이 동일한 저장소를 공유한다.

### Problem Frame
기존의 로컬 레포지토리 종속형 디자인 하니스(`design-harness`)는 단일 화면 후보를 생성하기 위해 20회 이상의 세부 CLI 호출과 엄격한 SHA-256 해시 추적, 임대(lease) 관리 등 지나치게 많은 트랜잭션 의례를 요구했다. 이로 인해 AI 코딩 에이전트가 화면 프로토타입을 빠르게 생성·탐색·비교하는 과정에서 심각한 병목과 파싱 에러를 겪었다. 또한 전송 계층 선택 시 "순수 MCP"는 웹 프리뷰 백그라운드 프로세스 및 포트 충돌 관리에 취약하고, "순수 FastAPI"는 에이전트의 직접 도구 호출에 불필요한 HTTP 통신 의례를 요구하는 문제가 있었다.

### Key Decisions
- **KD1 (Headless Domain Engine Core with Dual Adapters)**: 3계층 토큰 해석과 Jinja2 렌더링을 순수 Python 라이브러리로 분리하고, 상위에 MCP 어댑터와 ASGI 웹 어댑터를 얇은 래퍼로 구성한다. 단일 프로토콜 종속을 탈피하여 네트워크 목킹 없이 코어 비즈니스 로직을 100% 독립 테스트할 수 있는 구조를 확보한다. `Governs R1, R2, R3, R4, R7, R13`
- **KD2 (In-Process FastMCP / Embedded ASGI Preview with Process Tethering)**: MCP stdio 실행 시 백그라운드에서 동적 임시 포트(`port=0`) 루프백 ASGI 서버를 구동하며, 에이전트 stdio EOF 감지 시 500ms 이내에 자동 정리(Dead-Man's Switch)한다. 고정 포트 충돌 및 데몬/프로세스 누수를 원천 차단한다. `Governs R8, R9`
- **KD3 (Zero-Compile CSS Custom Property Injection for <16ms Hot-Reload)**: Astryx 토큰을 브라우저 CSS 변수로 매핑하고, `patch_tokens` 호출 시 WebSocket으로 토큰 델타를 주입하여 전체 HTML 재렌더링 없이 스타일을 즉시 모핑한다. 16ms 이내 초저지연 반응성을 보장하고 브라우저 입력 포커스 및 스크롤 위치를 보존한다. `Governs R10`
- **KD4 (Single-Source Pydantic v2 Schemas for MCP Tools & OpenAPI Specs)**: 토큰 계층 및 6종 도구 인터페이스를 Pydantic v2 모델로 정의하여 MCP JSONSchema와 FastAPI Swagger 문서를 단일 소스에서 자동 동기화하고 스키마 드리프트를 방지한다. `Governs R5, R12`
- **KD5 (Deterministic AST-Free Template Swizzle Exporter)**: `export_prototype`은 사전 검증된 컴포넌트 템플릿에 토큰을 1:1 치환하는 스위즐(swizzle) 방식으로 100% 문법 무결한 React/Tailwind 코드를 방출한다. `Governs R14, R15`
- **KD6 (Repository-Scoped SQLite Store with Postgres Extensibility)**: 레포지토리 단위 격리 원칙에 따라 프로젝트마다 `.protokflow/protokflow.db` SQLite 데이터베이스를 두고 SQLModel/SQLAlchemy로 디자인 시스템, `DESIGN.md` 마크다운 본문, 정규화된 토큰, 프로토타입 런/패치 이력을 영속화한다. 불필요한 다중 테넌시 복잡도를 배제하고, 향후 Postgres 확장 경로는 표준 SQL 호환성 및 타입 규율을 통해 보장한다. `Governs R17, R19, R20`
- **KD7 (DB-First Store with `DESIGN.md` File Projection)**: `DESIGN.md`의 내용은 DB를 정본으로 관리·편집되며, 파일 시스템의 파일은 Git 동기화를 위한 투영본으로 유지된다. `/admin` 저장은 파일로 즉시 write-through되고, 외부 변경(`git pull`, 브랜치 전환, 파일 직접 수정 등)은 **매 도구 호출 시 `(mtime, size)` 선검사**로 감지하여 자동 재인덱싱한다. Git 추적 대상인 `DESIGN.md`를 통해 데이터 손실 없는 복구 가능성을 보장한다. `Governs R16, R18, R20, R21`
- **KD8 (Self-Contained Sibling Design Systems with Derived Experiments)**: `DESIGN.md` 표준 규약에 따라 디자인 시스템은 계층적 상속 없이 **형제 관계의 자기완결 문서**로 모델링한다. 실험용 파생 디자인 시스템은 출처(`derived_from_id`) 메타데이터만 유지하고 완전히 해석된 토큰 트리를 독립 보유하며, 기본적으로 DB 내에서 탐색되다가 필요 시 명시적으로 파일로 export된다. `Governs R5, R22, R23`

### Actors
- **A1 (AI Coding Agent)**: Claude Desktop, Cursor, Codex 등 MCP 프로토콜을 통해 `create_prototype_run`, `patch_tokens`, `export_prototype` 도구를 직접 호출하는 주체.
- **A2 (Human Product Engineer / Designer)**: 에이전트와 대화하며 로컬 브라우저에서 생성된 다중 UI 후보군을 실시간 비교하고 피드백을 제공하는 최종 사용자.

### Requirements

#### Core Token Resolution, DESIGN.md & Database Store (`protokflow.core` & `protokflow.storage`)
- R1. Astryx 3계층 디자인 토큰 체계(`Foundations → Components → Patterns`)를 지원하고 토큰 캐스케이드 참조(`{colors.indigo-600}`, `{radii.md}`)를 결정론적으로 해석해야 한다.
- R2. 표준 UI 레이아웃 프리셋(`split-card`, `centered-modal`, `dashboard-shell`, `form-view` 등)을 내장하고 Jinja2 기반으로 1ms 이내 무오류(Zero-syntax-error) HTML을 렌더링해야 한다.
- R3. 모든 코어 엔진 로직은 네트워크나 I/O 전송 계층 의존성 없이 순수 Python 함수 및 Pydantic 모델로 동작해야 한다.
- R16. `DESIGN.md` 파일(YAML Front Matter + Markdown)을 파싱하고 정규화된 토큰 트리로 변환하거나 역으로 내보내는 양방향 직렬화기를 구현해야 한다. 왕복은 **무손실**이어야 한다 — 스펙이 정의한 `omitted`와 허용된 커스텀 확장 키(`unknown-key` 린트가 침묵하는 키)를 원문 그대로 보존해야 하며, 방출된 파일은 공식 린터(`npx @google/design.md lint`)를 통과해야 한다.
- R17. 레포당 하나의 SQLite DB를 사용하는 SQLModel/SQLAlchemy 기반 저장소를 구축하여 8개 테이블(`schema_meta`, `design_systems`, `design_tokens`, `prototype_runs`, `candidates`, `token_patches`, `slot_contents`, `exports`)로 상태를 영속화해야 한다. 상세 사양은 [데이터베이스 스키마 설계](../concepts/database-schema.md)를 단일 소스로 한다.
- R18. `/admin` 웹 라우트를 통해 브라우저에서 디자인 시스템 목록 조회, 신규 생성, `DESIGN.md` 마크다운 및 토큰을 시각적으로 편집할 수 있는 관리 UI를 제공해야 한다. 저장은 DB 반영과 동시에 대응 파일로 write-through되어야 하며, 파생 디자인 시스템의 원본 대비 diff를 표시해야 한다.
- R19. 런 데이터의 보존 정책을 제공해야 한다. 기본값으로 디자인 시스템당 최근 50개 런을 유지하고 초과분은 `archived` 처리 후 `protokflow prune`으로 삭제하며, 디자인 시스템과 토큰은 자동 삭제 대상이 아니다.
- R20. 부팅 시 `schema_meta.schema_version`을 검사해 코드가 기대하는 버전과 비교하고, 불일치 시 명확한 오류와 복구 안내를 제공해야 한다. DB 삭제 후 `DESIGN.md`로부터의 재인덱싱이 항상 유효한 복구 경로여야 한다.
- R21. 매 도구 호출 시 대응 `DESIGN.md` 파일의 `(mtime, size)`를 선검사하고, 불일치할 때만 sha256을 계산해 재인덱싱 여부를 판정해야 한다. `git pull`, 브랜치 전환, fresh clone, 에이전트의 파일 직접 편집을 모두 감지해야 하며, 진행 중인 런의 프리뷰는 재인덱싱의 영향을 받지 않아야 한다.
- R22. 파생 디자인 시스템을 생성·관리할 수 있어야 한다. 파생은 출처를 기록하되 완전히 해석된 자기완결 토큰 트리를 보유하고, 기본적으로 DB 전용이며 사용자의 명시적 요청 시에만 파일로 export되어야 한다.
- R23. 파일 탐색은 레포 루트의 `DESIGN.md`(= `default`)와 `design/{slug}.md`로 한정해야 한다. 하위 디렉토리에서 발견된 `DESIGN.md`는 부분 오버라이드가 아니라 **형제 디자인 시스템**으로 취급해야 한다.

#### MCP Protocol Adapter (`protokflow.adapters.mcp`)
- R4. Python 공식 `mcp` SDK 기반 stdio 및 SSE 전송 모드를 지원하며, `uvx protokflow mcp` 단일 명령으로 무설치 즉시 실행되어야 한다.
- R5. 핵심 MCP Tool Surface 6종(`create_prototype_run`, `patch_tokens`, `update_slot_custom`, `serve_preview`, `export_prototype`, `promote_tokens`)을 표준 JSONSchema로 노출해야 한다. `promote_tokens`는 소스(`{run_id, candidate_key}` | `{design_system}`)와 타깃(기존 | 신규)의 조합으로 **fork / capture / merge**를 모두 표현하며, `token_paths`로 부분 승격을 지원해야 한다.
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
  1. 에이전트가 `create_prototype_run` MCP 도구를 호출하며 대상 `design_system`, 목표, 변량 축(variation axes) 토큰을 전달. 호출 시점에 해당 디자인 시스템의 토큰이 런에 스냅샷으로 영속화됨.
  2. 코어 엔진이 토큰 캐스케이드를 해석하고 Jinja2 프리셋 템플릿으로 후보군 HTML을 렌더링 (<1ms).
  3. 어댑터가 동적 루프백 ASGI 서버를 바인딩하고 접속 URL 및 선택적 스크린샷 이미지를 반환.
- **Covers**: R1, R2, R4, R5, R6, R8, R21.

#### F2: Live Visual Feedback & Hot-Reload Loop
- **Trigger**: 사용자가 브라우저 프리뷰를 확인하고 토큰 수정을 요청.
- **Path**:
  1. 에이전트가 `patch_tokens` MCP 도구를 호출하여 특정 후보의 토큰 패치 전달.
  2. ASGI 서버가 WebSocket을 통해 대상 후보의 브라우저 뷰포트에 토큰 델타를 브로드캐스트.
  3. 브라우저가 CSS Custom Properties를 16ms 이내에 갱신하여 화면 새로고침 없이 즉시 반응.
  4. 문구·슬롯 콘텐츠 수정이 필요하면 에이전트가 `update_slot_custom`을 호출하여 해당 후보의 슬롯 텍스트를 갱신.
- **Covers**: R5, R7, R10, R11.

#### F3: Final Selection & Swizzle Code Export Flow
- **Trigger**: 사용자가 최종 후보를 확정하고 코드 반영을 요청.
- **Path**:
  1. 에이전트가 `export_prototype` MCP 도구를 호출 (`format: "react-tailwind"`).
  2. 코어 스위즐 엔진이 컴포넌트 템플릿에 최종 토큰을 주입하여 독립형 TSX 및 Tailwind 코드를 반환.
  3. 에이전트가 생성된 코드를 프로젝트 레포지토리 파일 시스템에 기록.
- **Covers**: R5, R14, R15.

#### F4: Derived Design System Exploration Loop
- **Trigger**: 기존 확정 디자인 시스템을 보존하면서 새로운 시각적 방향과 토큰 조합을 독립적으로 탐색하려 함.
- **Path**:
  1. 에이전트가 `promote_tokens`를 `source: {design_system: "default"}`, `target: {new: {...}}`로 호출하여 파생 디자인 시스템을 생성(**fork**). 파생은 DB 전용으로 생성되어 Git 작업 트리를 오염시키지 않음.
  2. 사용자가 파생 시스템으로 `create_prototype_run`을 반복 호출하며 여러 화면을 실험하고, `patch_tokens`로 토큰을 조정.
  3. 확정된 토큰 조합을 `promote_tokens` (`source: {run_id, candidate_key}`, `target: {design_system: "<파생>"}`)로 호출하여 파생 시스템에 반영(**capture**).
  4. 필요 시 export하여 `design/{slug}.md` 파일로 팀과 공유.
  5. 검증 완료 후 `promote_tokens` (`source: {design_system: "<파생>"}`, `target: {design_system: "default"}`, `token_paths: [...]`)를 호출하여 원본 디자인 시스템에 선택적 반영(**merge**). 원본은 파일 연동 상태이므로 write-through를 통해 `DESIGN.md`가 갱신되고 Git diff로 확인 가능.
- **Covers**: R5, R16, R18, R22.

#### F5: External File Change Reconciliation
- **Trigger**: `git pull`, 브랜치 전환, fresh clone, 또는 에이전트/사용자의 `DESIGN.md` 파일 직접 편집.
- **Path**:
  1. 다음 도구 호출 시 저장소 계층이 대응 파일의 `(mtime, size)`를 선검사.
  2. 불일치 시에만 sha256을 계산해 `source_digest`와 비교.
  3. 변경이 확인되면 해당 디자인 시스템을 재인덱싱(마크다운 본문, Front Matter, 토큰 전량 동기화). 진행 중인 런은 런 시점 스냅샷에 의해 격리되어 영향을 받지 않음.
- **Covers**: R16, R20, R21.

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

#### AE5: Fork, Explore, and Merge Back
- **Given**: 레포에 `DESIGN.md`(`default`)만 존재함.
- **When**: 에이전트가 `promote_tokens`로 `exp-violet` 파생을 만들고, 3회의 `create_prototype_run`과 `patch_tokens`로 색상을 탐색한 뒤, 최종 값을 `token_paths: ["colors.primary", "colors.primary-hover"]`로 `default`에 merge.
- **Then**: 파생은 DB에만 존재해 `git status`에 나타나지 않고, merge 후 루트 `DESIGN.md`의 해당 두 토큰만 변경되어 Git diff에 드러나며, 나머지 토큰과 마크다운 본문은 그대로 보존됨.
- **Covers**: R5, R16, R18, R22.

#### AE6: Lossless Round-Trip and Linter Conformance
- **Given**: 사용자의 `DESIGN.md`에 `omitted: [spacing]`과 커스텀 확장 키가 포함되어 있음.
- **When**: 파일을 인덱싱한 뒤 `/admin`에서 색상 토큰 하나를 수정하여 write-through가 발생.
- **Then**: 재작성된 파일에 `omitted` 선언과 커스텀 키가 그대로 남아 있고, 섹션 순서가 스펙의 정규 순서를 유지하며, `npx @google/design.md lint`가 새로운 경고 없이 통과함.
- **Covers**: R16, R18.

#### AE7: Reconciliation After `git pull`
- **Given**: MCP 서버가 동작 중이고 동료가 `DESIGN.md`의 `colors.primary`를 변경해 푸시함.
- **When**: 사용자가 `git pull` 후 별도 조작 없이 `create_prototype_run`을 호출.
- **Then**: 선검사가 변경을 감지해 재인덱싱이 선행되고 새 런은 갱신된 토큰으로 렌더링되며, 이전에 열려 있던 프리뷰 화면은 스냅샷 덕분에 그대로 유지됨.
- **Covers**: R20, R21.

### Scope Boundaries

#### In-Scope
- 순수 Python 기반 전송 독립형 3계층 토큰 해석 엔진 (`protokflow.core`).
- Google Labs `DESIGN.md` 파서/익스포터 및 YAML Front Matter ↔ 정규화 토큰 변환기.
- 레포지토리 단위 격리 SQLite DB 기반 디자인 시스템/토큰/런 이력 저장소 (`SQLModel` 기반, 8개 테이블).
- DB 우선 저장 + `DESIGN.md` 파일 투영(write-through) 및 매 호출 파일 상태 선검사·재인덱싱.
- 파생 디자인 시스템 생성과 `promote_tokens`의 fork/capture/merge 시맨틱.
- 무손실 Front Matter 라운드트립 및 공식 린터(`@google/design.md`) 적합성 검증.
- 브라우저 기반 디자인 시스템 & `DESIGN.md` 웹 어드민 UI (`/admin`), 파생 대비 diff 표시.
- 공식 Python SDK 기반 표준 MCP stdio/SSE 도구 어댑터 6종 (`protokflow.adapters.mcp`).
- Starlette/Uvicorn 기반 경량 ASGI 프리뷰 서버 및 동적 포트/수명주기 연동 (`protokflow.adapters.http`).
- WebSocket 기반 CSS Custom Property 마이크로 패치 (<16ms) 및 다중 뷰포트 매트릭스 UI.
- Pydantic v2 단일 소스 기반 MCP JSONSchema 및 OpenAPI 스펙 자동 동기화.
- 템플릿 스위즐 방식의 React/Tailwind 및 Vue 코드 추출 (`export_prototype`).

#### Deferred for Later
- 브라우저 내 실시간 토큰 슬라이더 직접 조작 UI (에이전트 기반 `promote_tokens` 워크플로우를 우선 지원).
- 기업 커스텀 디자인 시스템용 프로젝트별 로컬 템플릿 오버라이드 레지스트리 (`.protokflow/presets/`).
- 4개 이상 다중 후보군 렌더링 시 가상화 캔버스 최적화.

#### Outside Product Identity
- Figma, Adobe XD 등 클라우드 디자인 툴과의 실시간 양방향 동기화.
- 백엔드 REST/GraphQL API 호출 데이터 목킹 엔진.
- Git DAG 기반의 복잡한 3-Way Rebase 트랜잭션 관리 체계.
- 파일 간 계층적 상속/부분 오버라이드 체계 (DESIGN.md 표준 규약 준수 및 독립 완결성 보장).
- 멀티 테넌시 및 복잡한 행 단위 소유권 모델 (레포지토리 단위 로컬 격리 원칙).

### Success Criteria
- **SC1 (단순성)**: 에이전트가 단 1회의 MCP 도구 호출로 2개 이상의 브라우저 후보 화면을 즉시 띄울 수 있어야 함.
- **SC2 (무결성)**: Jinja2 템플릿 토큰 주입 및 React 컴포넌트 코드 추출 시 문법/파싱 에러가 0건이어야 하며, 방출된 `DESIGN.md`가 공식 린터에서 새로운 경고 0건이어야 함.
- **SC3 (반응성)**: `patch_tokens` 호출 시 브라우저 CSS 변수 핫리로드 반응 속도가 16ms 이내여야 함.
- **SC4 (배포성)**: `uvx protokflow mcp` 명령 하나로 Claude Desktop, Codex, Cursor 등 주요 에이전트 환경에서 즉시 연동 가능해야 함.
- **SC5 (격리성)**: 코어 비즈니스 로직 단위 테스트가 네트워크 목킹 없이 10ms 이내에 통과해야 함.
- **SC6 (복구성)**: `.protokflow/protokflow.db`를 삭제해도 레포의 `DESIGN.md` 파일들로부터 모든 디자인 시스템과 토큰이 완전히 복원되어야 함(런 이력은 소멸을 허용).
