---
# Brand tokens — hand-maintained. Keep the comments, they are load-bearing
# for the humans who edit this file in review.
version: alpha
name: 'Nocturne Ops'          # single-quoted on purpose
description: >-
  A dark operations console theme.
  Folded scalar, two source lines, one logical value.

# Sections we deliberately do not define.
omitted:
  - spacing
  - section: rounded
    reason: "No rounded corners defined in brand book"

# Unknown top-level key — spec says consumers preserve unknown content.
iconography:
  set: lucide
  stroke: 1.5

colors:
  primary: "#0B0E14"
  secondary: "#7A8290"
  tertiary: '#E4572E'
  neutral: "#F2F4F7"
  surface: "#11151C"
  on-surface: "#E6EAF2"
  error: "#D93025"

typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 40px
    fontWeight: 700           # bare number
    lineHeight: 1.15
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: "400"         # quoted number — spec says equivalent
    lineHeight: 1.6
  telemetry-data:             # unknown token name — spec says accept
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "0.02em"

components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.neutral}"
    padding: 12px
  input-text:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    borderColor: "{colors.secondary}"   # unknown component property
    typography: "{typography.body-md}"
---

# Nocturne Ops

## Overview

A dark operations console for sustained monitoring work.

## Iconography

Unknown section heading — the spec says preserve it, do not error.

## Colors

- **Primary (#0B0E14):** Near-black ink for chrome and dense surfaces.
- **Tertiary (#E4572E):** The sole interaction accent.

## Typography

Inter for the interface, JetBrains Mono for telemetry.

## Components

Buttons and inputs only; this system is deliberately small.

## Do's and Don'ts

- Do keep telemetry in the monospace label style
- Don't introduce a second accent color
