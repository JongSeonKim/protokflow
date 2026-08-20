# Protokflow 디자인 토큰 3계층 아키텍처 가이드 (Astryx 기반)

Meta의 디자인 시스템 **Astryx**의 설계를 벤치마킹하여, `Protokflow`에서 채택한 **Foundations → Components → Patterns** 3계층 토큰 체계와 렌더링/코드 추출 가이드입니다.

---

## 1. 계층별 구조 및 역할 (3-Tier Architecture)

```text
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Foundations (기초 원시 토큰)                       │
│  - 팔레트 색상, 서체, 곡률(Radius), 간격(Spacing), 그림자 등   │
└──────────────────────────────┬──────────────────────────────┘
                               │ 참조
┌──────────────────────────────▼──────────────────────────────┐
│  Layer 2: Components (컴포넌트 시맨틱 토큰)                  │
│  - 버튼, 인풋, 뱃지, 카드 등 개별 UI 부품의 시각 속성        │
└──────────────────────────────┬──────────────────────────────┘
                               │ 조합 및 배치
┌──────────────────────────────▼──────────────────────────────┐
│  Layer 3: Patterns (패턴 및 화면 레이아웃 토큰)              │
│  - split-card, data-table, modal 등 완성형 화면 구조 및 카피  │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 실제 데이터 구조 예시 (경성오락관 로그인 화면)

### Layer 1: Foundations (기초 원시 토큰)
디자인 시스템의 가장 밑바탕이 되는 글로벌 속성들입니다.

```json
{
  "foundations": {
    "colors": {
      "indigo-900": "#1E1B4B",
      "indigo-600": "#4F46E5",
      "indigo-500": "#6366F1",
      "slate-800": "#1E293B",
      "slate-500": "#64748B",
      "slate-200": "#E2E8F0",
      "rose-600": "#E11D48",
      "white": "#FFFFFF"
    },
    "radii": {
      "sm": "6px",
      "md": "8px",
      "lg": "16px",
      "xl": "20px"
    },
    "typography": {
      "font-sans": "Pretendard, -apple-system, sans-serif"
    }
  }
}
```

---

### Layer 2: Components (컴포넌트 시맨틱 토큰)
기초 토큰을 참조하여 버튼, 입력창, 뱃지 등의 역할을 정의합니다.

```json
{
  "components": {
    "primary-button": {
      "background": "{colors.indigo-600}",
      "text": "{colors.white}",
      "radius": "{radii.md}",
      "padding": "14px",
      "hover-background": "{colors.indigo-500}"
    },
    "text-input": {
      "border": "{colors.slate-200}",
      "radius": "{radii.md}",
      "text": "{colors.slate-800}",
      "focus-border": "{colors.indigo-600}",
      "error-border": "{colors.rose-600}"
    },
    "brand-badge": {
      "background": "rgba(255, 255, 255, 0.15)",
      "text": "{colors.white}",
      "radius": "{radii.sm}"
    }
  }
}
```

---

### Layer 3: Patterns (패턴/화면 조합 토큰: `split-card`)
최상위 완성형 레이아웃 템플릿에 레이어 1, 2의 컴포넌트들을 배치하고 카피/상태를 주입합니다.

```json
{
  "pattern": {
    "type": "split-card",
    "layout": {
      "mode": "modal",             // modal (중앙 플로팅) 또는 fullscreen (전체 화면)
      "ratio": "50:50",
      "max-width": "960px",
      "container-radius": "{radii.xl}"
    },
    "left-brand-panel": {
      "background": "linear-gradient(135deg, {colors.indigo-900} 0%, {colors.indigo-600} 100%)",
      "badge-text": "GSPLAY CONSOLE",
      "title": "경성오락관 관리자 로그인",
      "subtitle": "시니어 라이프스타일 및 엔터테인먼트 서비스를 위한 통합 관리자 플랫폼",
      "copyright": "© 2026 GSPlay. All rights reserved."
    },
    "right-form-panel": {
      "title": "로그인",
      "subtitle": "관리자 계정 정보를 입력해 주세요.",
      "fields": [
        { "id": "username", "label": "관리자 아이디", "placeholder": "admin_operator" },
        { "id": "password", "label": "비밀번호", "placeholder": "••••••••", "has-toggle": true }
      ],
      "auxiliary-link": { "text": "비밀번호 찾기" },
      "submit-button": { "component": "primary-button", "text": "로그인" }
    }
  }
}
```

---

## 3. 에이전트와 MCP 서버의 상호작용 흐름

### 1단계: 초기 후보군 생성 (`create_prototype_run`)
에이전트는 복잡한 마크업 대신 최상위 패턴 및 변량 축 토큰만 전달합니다.
```json
{
  "screen_goal": "경성오락관 관리자 2열 분할 로그인 화면",
  "layout_preset": "split-card",
  "variation_axes": ["layout.mode"],
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

### 2단계: Jinja2 템플릿의 자동 토큰 해석 (Cascade & Resolve)
- `Protokflow` 내부 엔진이 `{colors.indigo-600}`, `{radii.md}` 등의 토큰 참조를 자동 해소합니다.
- HTML 인라인 따옴표 충돌이나 문법 오류 없이 100% 검증된 정적 HTML/CSS를 1ms 이내로 렌더링하고 브라우저 프리뷰 서버를 기동합니다.

### 3단계: 부분 커스터마이징 (`patch_tokens`)
사용자가 "브랜드 색상을 딥 네이비로 바꾸고 로그인 버튼만 라운드를 더 줘"라고 요청하면:
```json
{
  "run_id": "run-login-01",
  "candidate_id": "c1",
  "token_patches": {
    "foundations.colors.indigo-900": "#0F172A",
    "components.primary-button.radius": "12px"
  }
}
```
- WebSocket을 통해 브라우저 프리뷰 화면이 새로고침 없이 즉각 핫리로드(Hot-Reload)됩니다.

### 4단계: 프로덕션 코드 내보내기 (`export_prototype`)
확정된 후보 화면을 Astryx의 `swizzle` 방식처럼 실제 프로젝트의 단독 React/Tailwind 컴포넌트로 내보냅니다.

```tsx
// export_prototype 출력 예시: src/features/auth/views/LoginView.tsx
export function LoginView() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-6 font-sans">
      <div className="w-full max-w-[960px] min-h-[560px] flex rounded-[20px] shadow-2xl overflow-hidden bg-white">
        {/* Left Brand Panel */}
        <div className="w-1/2 bg-gradient-to-br from-[#1E1B4B] to-[#4F46E5] text-white p-12 flex flex-col justify-between">
          <div>
            <span className="inline-block px-3 py-1 bg-white/15 rounded-[6px] text-xs font-semibold tracking-wide mb-6">
              GSPLAY CONSOLE
            </span>
            <h1 className="text-3xl font-bold leading-tight mb-4">
              경성오락관<br />관리자 로그인
            </h1>
            <p className="text-indigo-100 text-sm leading-relaxed">
              시니어 라이프스타일 및 엔터테인먼트 서비스를 위한 통합 관리자 플랫폼
            </p>
          </div>
          <p className="text-xs text-indigo-300">© 2026 GSPlay. All rights reserved.</p>
        </div>

        {/* Right Form Panel */}
        <div className="w-1/2 p-12 flex flex-col justify-center bg-white">
          <h2 className="text-2xl font-bold text-slate-800 mb-2">로그인</h2>
          <p className="text-sm text-slate-500 mb-7">관리자 계정 정보를 입력해 주세요.</p>
          
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">관리자 아이디</label>
              <input className="w-full px-3.5 py-3 rounded-md border border-slate-200 text-sm focus:border-indigo-600 focus:outline-none" placeholder="admin_operator" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">비밀번호</label>
              <input type="password" className="w-full px-3.5 py-3 rounded-md border border-slate-200 text-sm focus:border-indigo-600 focus:outline-none" placeholder="••••••••" />
            </div>
            <div className="flex justify-end">
              <button type="button" className="text-xs text-indigo-600 font-medium hover:underline">비밀번호 찾기</button>
            </div>
            <button type="button" className="w-full py-3.5 bg-indigo-600 text-white rounded-md text-sm font-semibold hover:bg-indigo-500 transition-colors">
              로그인
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

---

## 4. 핵심 기대 효과
1. **에이전트 조작 안정성**: AI가 복잡한 HTML 문자열을 조립하지 않고 JSON 토큰만 다루므로 파싱/문법 에러 원천 차단.
2. **높은 커스터마이징 유연성**: 기초 값(`Foundations`), 위젯 속성(`Components`), 화면 배치(`Patterns`)의 어느 계층이든 자유롭게 부분 수정 가능.
3. **프로덕션 직결성**: 프로토타입 단계에서 합의된 시각 규격이 손실 없이 React/Tailwind 코드로 1:1 변환.

