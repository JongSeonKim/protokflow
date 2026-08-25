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
