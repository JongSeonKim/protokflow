---
version: alpha
name: Daylight Prestige
description: A high-contrast editorial system for long-form product surfaces.
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
  none: 0px
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
---

# Daylight Prestige

## Overview

Daylight Prestige is a calm, institutional system built for readers who stay on
a page. It favours permanence over novelty: heavy neutrals, one earthy accent,
and generous vertical rhythm.

## Colors

The palette is rooted in high-contrast neutrals and a single evocative accent.

- **Primary (#1A1C1E):** A deep ink used for headlines and core text.
- **Secondary (#6C7278):** A sophisticated slate for borders and metadata.
- **Tertiary (#B8422E):** A vibrant earthy red, the sole driver for interaction.
- **Neutral (#F7F5F2):** A warm limestone foundation for all pages.

## Typography

Two weights of **Public Sans** carry the narrative; **Space Grotesk** carries
technical data.

- **Headlines:** Public Sans Semi-Bold for an institutional voice.
- **Body:** Public Sans Regular at 16px for long-form readability.
- **Labels:** Space Grotesk, uppercase, with generous letter spacing.

## Layout

A fixed-max-width grid (1200px) on desktop, fluid on mobile. A strict 8px
spacing scale with a 4px half-step maintains rhythm.

## Elevation & Depth

Depth is tonal rather than shadowed. Backgrounds use warm limestone; primary
content sits on pure white cards.

## Shapes

Architectural sharpness. Interactive elements use a minimal 8px corner radius.

## Components

Buttons carry the accent only for the single most important action per screen.
Input fields inherit body typography and the standard 8px radius.

## Do's and Don'ts

- Do use the tertiary color only for the single most important action per screen
- Don't mix rounded and sharp corners in the same view
- Do maintain WCAG AA contrast ratios (4.5:1 for normal text)
- Don't use more than two font weights on a single screen
