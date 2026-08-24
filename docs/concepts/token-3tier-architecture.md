# Protokflow 디자인 토큰 아키텍처 및 DESIGN.md 저장소 가이드

Protokflow는 Google Labs의 **DESIGN.md 표준 포맷**(YAML Front Matter + Markdown)과 Meta Astryx의 **3계층 토큰 분리 철학**을 결합하여, AI 에이전트와 인간 개발자가 단일 문서와 DB 디자인 시스템을 통해 상호작용할 수 있는 디자인 시스템 엔진을 제공한다.

---

## 1. 계층별 구조 및 역할 (3-Tier Architecture & DESIGN.md)

Protokflow는 디자인 명세(Spec)와 런타임 레이아웃(Runtime Layout)을 명확히 분리한다.

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

`DESIGN.md`는 상단의 **YAML Front Matter**(기계 판독용 토큰 정의)와 하단의 **Markdown Body**(에이전트 및 인간을 위한 맥락/가이드라인)로 구성된다.

이 절의 규격은 `@google/design.md` 패키지가 동봉하는 정본 스펙(`dist/spec.md`, `dist/spec-config.yaml`)을 단일 소스로 하며, 아래 예시는 공식 린터를 경고 없이 통과한다.

### Front Matter 스키마

| 키 | 타입 | 비고 |
|---|---|---|
| `version` | string | 현재 `alpha` |
| `name` | string | 디자인 시스템 이름 |
| `description` | string | 선택 |
| `omitted` | string[] \| `{section, reason}`[] | 의도적으로 정의하지 않은 섹션 선언. `missing-sections` 경고를 억제 |
| `colors` | map\<string, Color\> | |
| `typography` | map\<string, **Typography**\> | 값은 스칼라가 아니라 **중첩 객체** |
| `rounded` | map\<string, Dimension\> | |
| `spacing` | map\<string, Dimension \| number\> | |
| `components` | map\<string, map\<string, string\>\> | |

**Typography 속성** (그 외 키는 경고): `fontFamily`, `fontSize`, `fontWeight`, `lineHeight`, `letterSpacing`, `fontFeature`, `fontVariation`.

**컴포넌트 서브토큰** (그 외 키는 `broken-ref` 경고): `backgroundColor`, `textColor`, `typography`, `rounded`, `padding`, `size`, `height`, `width`.

`Dimension`의 허용 단위는 `px`, `em`, `rem`이다. `Color`는 유효한 CSS 색상 문자열(hex, named, `rgb()`, `hsl()`, `oklch()`, `color-mix()` 등)을 지원하며, 대비 검사를 위해 내부적으로 sRGB로 변환되지만 원문 표기는 보존된다.

토큰 참조는 `{path.to.token}` 형식이다. 대부분의 그룹에서는 원시값을 가리켜야 하며, `components` 안에서만 복합값 참조(`{typography.label-md}`)가 허용된다.

### Markdown Body 섹션

모든 섹션은 `##`(h2)이며, 존재하는 섹션은 아래 순서를 준수해야 한다(`section-order` 린트). 문서 제목용 `#`(h1)은 섹션으로 파싱되지 않는다.

1. **Overview** (별칭: Brand & Style)
2. **Colors**
3. **Typography**
4. **Layout** (별칭: Layout & Spacing)
5. **Elevation & Depth** (별칭: Elevation)
6. **Shapes**
7. **Components**
8. **Do's and Don'ts**

스펙에 정의되지 않은 섹션 제목(`## Iconography` 등)은 보존되며 유효하다. 반면 동일한 섹션 제목이 중복되면 파일 파싱이 거부된다.

### 예시

```markdown
---
version: alpha
name: Acme Console
description: 밀도 높은 데이터 화면을 위한 내부 운영 콘솔 시스템.
colors:
  primary: "#1A1C1E"
  secondary: "#6C7278"
  tertiary: "#B8422E"
  neutral: "#F7F5F2"
  surface: "#FFFFFF"
  on-surface: "#1A1C1E"
  error: "#B3261E"
typography:
  headline-lg:
    fontFamily: Public Sans
    fontSize: 48px
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  body-md:
    fontFamily: Public Sans
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
  label-md:
    fontFamily: Space Grotesk
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.1em"
rounded:
  sm: 4px
  md: 8px
  lg: 12px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 32px
  gutter: 24px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: 12px
    typography: "{typography.label-md}"
  button-primary-hover:
    backgroundColor: "{colors.secondary}"
  button-secondary:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    padding: 12px
---

# Acme Console

## Overview
고효율의 비즈니스 생산성을 지원하는 직관적이고 군더더기 없는 데이터 밀도 중심의 인터페이스를 지향합니다.

## Colors
- **Primary (#1A1C1E):** 헤드라인과 본문 텍스트의 기준 색.
- **Tertiary (#B8422E):** 화면당 하나의 주요 액션에만 사용하는 강조색.

## Typography
- 데이터 테이블 및 폼 레이블은 가독성을 위해 14~16px 기준 고대비(WCAG AA 4.5:1 이상)를 유지합니다.
- 시각적 위계를 위해 헤딩과 본문, 캡션 간의 명확한 서체 크기 및 굵기 대비를 유지합니다.

## Components
버튼과 입력 필드를 정의합니다. 변형 상태는 `button-primary-hover`처럼 관련 키로 분리합니다.

## Do's and Don'ts
- **Do**: 모든 핵심 CTA 버튼은 명확한 레이블과 44px 이상의 인터랙션 영역을 유지합니다.
- **Don't**: 상태 표시 색상을 브랜드 장식용 배경으로 남용하지 않습니다.
```

### YAML 앵커 및 별칭 사용 제한 규약

Front Matter 내 YAML 앵커(`&name`) 및 별칭(`*name`) 사용은 허용되지 않는다. DESIGN.md 표준 참조 문법은 `{path.to.token}` 문자열 형식이며, 이는 양방향 직렬화 과정에서 무손실 보존된다. 반면 YAML 파서가 로드 시점에 앵커/별칭을 사전 역참조(dereference)할 경우, in-place 토큰 패치 시 별칭 노드가 정적 값으로 고착화되어 참조 무결성이 훼손된다. 따라서 Protokflow는 파일 인덱싱 시점에 YAML 앵커/별칭을 감지하면 명시적 오류를 발생시켜 처리를 중단한다.

---

## 3. 다중 디자인 시스템과 DESIGN.md 동기화

Protokflow는 로컬 단독 개발 환경을 위한 임베디드 **SQLite**(`.protokflow/protokflow.db`)를 기본 저장소로 사용하며, **SQLAlchemy** 추상화를 통해 향후 **Postgres** 엔터프라이즈 환경으로 확장이 가능하다.

디자인 시스템은 프로젝트 내 여러 테마/컨텍스트(예: `default`, `admin-dark`, `mobile`)를 격리 관리하는 단위이며, 하나의 디자인 시스템은 하나의 `DESIGN.md`(Markdown 가이드 본문 + Layer 1/2 토큰 트리)에 1:1로 대응한다. Layer 3(Patterns)는 디자인 시스템에 저장되지 않고 프로토타입 런 실행 시점에 결정되는 런타임 파라미터다.

각 디자인 시스템은 **자기완결 문서**다. DESIGN.md 스펙에는 계층·상속·오버라이드 개념이 없고, 토큰 참조는 동일 파일 내에서 완결되어야 한다(`broken-ref` 린트). 따라서 하위 디렉토리의 `DESIGN.md`도 부분 오버라이드가 아닌 형제 디자인 시스템으로 취급한다.

```
repo/
├─ DESIGN.md          → 'default'
└─ design/
   ├─ admin-dark.md   → 'admin-dark'
   └─ mobile.md       → 'mobile'
```

> 테이블 정의, 컬럼, 제약 조건 등 구체적인 데이터베이스 스키마는 이 문서의 범위가 아니다. [데이터베이스 스키마 설계](./database-schema.md)를 참조한다.

### 저장소 위상

`DESIGN.md`는 **DB에 저장되고 DB에서 편집**된다. 레포지토리의 `DESIGN.md` 파일은 그 투영본이며, Git을 통한 팀 동기화 채널이자 표준 상호운용 포맷 역할을 수행한다. DB(`.protokflow/protokflow.db`)는 gitignore 대상이므로 언제든 파일로부터 재구축할 수 있다.

### 관리 및 동기화 흐름
1. **Web UI 관리**: 웹 브라우저(`/admin`)에서 디자인 시스템별 `DESIGN.md` 마크다운과 토큰을 시각적으로 편집 및 생성. 저장은 DB에 반영되는 동시에 `DESIGN.md` 파일로 **즉시 write-through** 되어 Git 변경 사항으로 노출된다. write-through는 보존된 Front Matter 원문(`design_systems.front_matter_raw`)을 기반으로 **대상 토큰만 in-place 치환**하므로, 주석·공백·따옴표 스타일·키 순서가 온전히 보존되고 단일 토큰 변경 시 `git diff` 1줄 변경으로 국소화된다.
2. **에이전트 컨텍스트 제공**: 에이전트가 `design://systems/{id}` 리소스를 요청하면 DB에 저장된 마크다운 가이드와 토큰을 즉시 반환하여 프롬프트 컨텍스트에 주입한다.
3. **파일 → DB 상시 선검사**: `git pull`, 브랜치 전환, 파일 직접 수정 등 외부 변경 가능성에 대응하여, 매 도구 호출 시 `(mtime, size)`를 선검사하고 불일치 시에만 해시를 비교해 자동 재인덱싱한다.

---

## 4. Layer 3(Patterns)와의 결합 및 프로토타이핑 워크플로우

### 1단계: 프로토타입 생성 요청 (`create_prototype_run`)
에이전트는 대상 `design_system`과 템플릿 `layout_preset`을 지정하여 호출한다.
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
- 선택된 디자인 시스템의 Foundations/Components 토큰과 Layer 3 Pattern 파라미터를 결합하여 Jinja2 템플릿을 정적 HTML/CSS로 컴파일한다.

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
- WebSocket을 통해 브라우저 프리뷰 화면의 CSS 변수가 16ms 이내로 즉각 모핑되며 변경 내역은 DB에 기록된다.

### 4단계: 프로덕션 코드 내보내기 (`export_prototype`)
- 확정된 화면의 스펙을 검증된 템플릿 기반 스위즐(swizzle) 방식으로 문법 무결한 React/Tailwind 코드로 추출한다.
