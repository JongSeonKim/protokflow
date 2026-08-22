# Protokflow 디자인 토큰 아키텍처 및 DESIGN.md 저장소 가이드

Protokflow는 Google Labs의 **DESIGN.md 표준 포맷**(YAML Front Matter + Markdown)과 Meta Astryx의 **3계층 토큰 분리 철학**을 결합하여, AI 에이전트와 인간 개발자가 단일 문서와 DB 디자인 시스템을 통해 상호작용할 수 있는 디자인 시스템 엔진을 제공합니다.

---

## 1. 계층별 구조 및 역할 (3-Tier Architecture & DESIGN.md)

Protokflow는 디자인 명세(Spec)와 런타임 레이아웃(Runtime Layout)을 명확히 분리합니다.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│  [ DESIGN.md / DB Store ]                                           │
│  Layer 1: Foundations (기초 원시 토큰) - colors, typography, rounded...   │
│  Layer 2: Components (컴포넌트 시맨틱 토큰) - buttons, inputs, cards...   │
│  Markdown Body: 철학, 브랜드 가이드라인, Do's & Don'ts, 타이포 규칙      │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ 토큰 참조 & 바인딩
┌────────────────────────────────────▼────────────────────────────────────┐
│  [ Protokflow Runtime Templates ]                                       │
│  Layer 3: Patterns (화면 레이아웃 프리셋 및 컴포넌트 조합)              │
│  - split-card, centered-modal, dashboard-shell, data-table              │
│  - 레이아웃 모드, 패널 비율, 슬롯 콘텐츠 주입                           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. DESIGN.md 표준 데이터 구조

`DESIGN.md`는 상단의 **YAML Front Matter**(기계 판독용 토큰 정의)와 하단의 **Markdown Body**(에이전트 및 인간을 위한 맥락/가이드라인)로 구성됩니다.

```markdown
---
colors:
  primary: "#4F46E5"
  primary-hover: "#6366F1"
  background: "#FFFFFF"
  surface: "#F8FAFC"
  text: "#1E293B"
  text-muted: "#64748B"
  border: "#E2E8F0"
  danger: "#E11D48"

typography:
  font-family: "Pretendard, -apple-system, sans-serif"
  base-size: "16px"
  line-height: "1.5"

rounded:
  sm: "6px"
  md: "8px"
  lg: "16px"
  xl: "20px"

spacing:
  unit: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.md}"
    padding: "12px 20px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  input-text:
    borderColor: "{colors.border}"
    rounded: "{rounded.md}"
    textColor: "{colors.text}"
    focusBorderColor: "{colors.primary}"
    errorBorderColor: "{colors.danger}"
  badge-brand:
    backgroundColor: "rgba(79, 70, 229, 0.1)"
    textColor: "{colors.primary}"
    rounded: "{rounded.sm}"
---

# 엔터프라이즈 SaaS 콘솔 디자인 시스템 가이드

## 브랜드 철학
고효율의 비즈니스 생산성을 지원하는 직관적이고 군더더기 없는 데이터 밀도 중심의 인터페이스를 지향합니다.

## 타이포그래피 및 가독성 규칙
- 데이터 테이블 및 폼 레이블은 가독성을 위해 14~16px 기준 고대비(WCAG AA 기준 4.5:1 이상)를 유지합니다.
- 시각적 위계를 위해 헤딩과 본문, 캡션 간의 명확한 서체 크기 및 굵기 대비를 유지합니다.

## Do's and Don'ts
- **Do**: 모든 핵심 CTA 버튼은 명확한 레이블과 44px 이상의 인터랙션 영역을 유지합니다.
- **Don't**: 상태 표시 색상(Primary, Danger, Warning 등)을 브랜드 장식용 배경으로 남용하지 않습니다.
```

---

## 3. 다중 디자인 시스템과 DESIGN.md 동기화

Protokflow는 로컬 단독 개발 환경을 위한 임베디드 **SQLite**(`.protokflow/protokflow.db`)를 기본 저장소로 사용하며, **SQLAlchemy/SQLModel** 추상화를 통해 향후 **Postgres** 엔터프라이즈 환경으로 확장이 가능합니다.

디자인 시스템은 프로젝트 내 여러 테마/컨텍스트(예: `default`, `admin-dark`, `mobile`)를 격리 관리하는 단위이며, 하나의 디자인 시스템은 하나의 `DESIGN.md`(Markdown 가이드 본문 + Layer 1/2 토큰 트리)에 1:1로 대응합니다. Layer 3(Patterns)는 디자인 시스템에 저장되지 않고 프로토타입 런 실행 시점에 결정되는 런타임 파라미터입니다.

각 디자인 시스템은 **자기완결 문서**입니다. DESIGN.md 스펙에는 계층·상속·오버라이드 개념이 없고, 토큰 참조는 같은 파일 안에서 해석되어야 합니다(`broken-ref` 린트). 따라서 하위 디렉토리의 `DESIGN.md`도 부분 오버라이드가 아니라 형제 디자인 시스템으로 취급합니다.

```
repo/
├─ DESIGN.md          → 'default'
└─ design/
   ├─ admin-dark.md   → 'admin-dark'
   └─ mobile.md       → 'mobile'
```

> 테이블 정의, 컬럼, 제약 조건 등 구체적인 데이터베이스 스키마는 이 문서의 범위가 아닙니다. [데이터베이스 스키마 설계](./database-schema.md)를 참조하세요.

### 저장소 위상

`DESIGN.md`는 **DB에 저장되고 DB에서 편집**됩니다. 레포의 `DESIGN.md` 파일은 그 투영본이며, git을 통한 팀 동기화 채널이자 표준 상호운용 포맷 역할을 합니다. DB(`.protokflow/protokflow.db`)는 gitignore 대상이므로 언제든 파일로부터 재구축할 수 있습니다.

### 관리 및 동기화 흐름
1. **Web UI 관리**: 웹 브라우저(`/admin`)에서 디자인 시스템별 `DESIGN.md` 마크다운과 토큰을 시각적으로 편집 및 생성. 저장은 DB에 반영되는 동시에 `DESIGN.md` 파일로 **즉시 write-through** 되어 git이 변경을 보게 됩니다.
2. **에이전트 컨텍스트 제공**: 에이전트가 `design://systems/{id}` 리소스를 요청하면 DB에 저장된 마크다운 가이드와 토큰을 즉시 반환하여 프롬프트 컨텍스트에 주입.
3. **파일 → DB 상시 선검사**: `git pull`, 브랜치 전환, 에이전트의 파일 직접 편집 등 외부 변경이 발생할 수 있으므로, 매 도구 호출 시 `(mtime, size)`를 검사하고 불일치할 때만 해시를 비교해 재인덱싱합니다.

---

## 4. Layer 3(Patterns)와의 결합 및 프로토타이핑 워크플로우

### 1단계: 프로토타입 생성 요청 (`create_prototype_run`)
에이전트는 대상 `design_system`과 템플릿 `layout_preset`을 지정하여 호출합니다.
```json
{
  "design_system": "admin-dark",
  "screen_goal": "엔터프라이즈 콘솔 2열 분할 로그인 화면",
  "layout_preset": "split-card",
  "variation_axes": ["pattern.layout.mode"],
  "candidates": [
    {
      "id": "c1",
      "label": "50:50 플로팅 모달형",
      "tokens": { "pattern.layout.mode": "modal", "pattern.layout.ratio": "50:50" }
    },
    {
      "id": "c2",
      "label": "50:50 풀스크린 분할형",
      "tokens": { "pattern.layout.mode": "fullscreen", "pattern.layout.ratio": "50:50" }
    }
  ]
}
```

### 2단계: 런타임 토큰 캐스케이드 해석 및 초고속 렌더링 (<1ms)
- 선택된 디자인 시스템의 Foundations/Components 토큰과 Layer 3 Pattern 파라미터를 결합하여 Jinja2 템플릿을 정적 HTML/CSS로 컴파일합니다.

### 3단계: WebSocket 초저지연 토큰 핫패치 (`patch_tokens`)
```json
{
  "run_id": "run-login-01",
  "candidate_id": "c1",
  "token_patches": {
    "colors.primary": "#1E1B4B",
    "components.button-primary.rounded": "12px"
  }
}
```
- WebSocket을 통해 브라우저 프리뷰 화면의 CSS 변수가 <16ms 이내로 즉각 모핑되며 변경 내역은 DB에 기록됩니다.

### 4단계: 프로덕션 코드 내보내기 (`export_prototype`)
- 확정된 화면의 스펙을 검증된 템플릿 기반 스위즐(swizzle) 방식으로 100% 무오류 React/Tailwind 코드로 추출합니다.
