# Fonts

The default typography uses a professional **system font stack** (see
`fap/theme/typography.py`) — no network fonts, nothing to bundle.

To use a custom brand face, drop the `.woff2` files here and point
`Typography.font_sans` at the family name via branding configuration
(`[branding] font = "Your Font, -apple-system, sans-serif"`), then add an
`@font-face` block in `fap/theme/css.py`. Nothing else changes.
