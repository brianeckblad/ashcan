# Palette Trial Notes

This file documents the April 2026 palette trial requested for the UI tokens.

## Trial palette

- Neutrals: `#918D8A`, `#E8E8E6`, `#636261`, `#ADADAD`, `#464243`, `#C5C2BE`
- Primary accent: `#E2E800`
- Secondary accent: `#5C9EB8`

## Token mapping

- `--color-bg`: `#2F2C2D`
- `--color-surface`: `#3A3738`
- `--color-elevated`: `#474445`
- `--color-inset`: `#282526`
- `--color-text`: `#E8E8E6`
- `--color-text-muted`: `#C5C2BE`
- `--color-text-dim`: `#ADADAD`
- `--color-accent`: `#E2E800`
- `--color-accent-2`: `#5C9EB8`

### Readability follow-up (darker surfaces)

- `--color-border`: `#5A5758`
- `--color-border-hover`: `#7A7778`
- `--color-status-surface`: `#312E2F`

This darker pass keeps the same palette family but improves contrast for white and blue UI elements.

## Usage intent

- Use `--color-accent` (`#E2E800`) for high-visibility emphasis and primary CTA moments.
- Use `--color-accent-2` (`#5C9EB8`) for secondary emphasis, focus outlines, and supportive actions.
- Keep semantic states (`danger`, `success`, `warning`, `info`) separate from accent tokens.
- Keep all UI color usage wired through tokens and shared components; avoid template-specific color overrides.

## Files updated

- `app/static/css/tokens.css`
- `app/static/css/palette-trial-notes.md`

