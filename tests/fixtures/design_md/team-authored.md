---
version: alpha
name: Acme Console

# 2026-08 브랜드 리프레시. primary/tertiary는 브랜드팀 승인 필요.
# 변경 시 #design-system 채널에 공유할 것.
colors:
  primary: "#1A1C1E"      # 승인됨 2026-08-11
  secondary: "#6C7278"
  tertiary: "#B8422E"     # 접근성 검토 완료 (AA)
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
  body-md:
    fontFamily: Public Sans
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6

rounded:
  sm: 4px
  md: 8px
  lg: 12px

spacing:
  sm: 8px
  md: 16px
  lg: 32px

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: 12px
---

# Acme Console

## Overview

내부 운영 콘솔. 밀도 높은 데이터 화면에서 장시간 작업하는 사용자를 위한 시스템.

## Colors

- **Primary (#1A1C1E):** 헤드라인과 본문 텍스트.
- **Tertiary (#B8422E):** 화면당 하나의 주요 액션에만 사용.

## Typography

Public Sans 단일 서체. 헤드라인 600, 본문 400.

## Components

버튼과 입력 필드만 정의합니다.

## Do's and Don'ts

- Do 화면당 tertiary 사용은 1회로 제한
- Don't 두 가지 이상의 서체 굵기를 한 화면에 혼용
