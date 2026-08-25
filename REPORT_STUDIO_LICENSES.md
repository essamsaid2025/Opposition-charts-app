# Report Studio — Dependency Licenses

Hard product requirement: **every Report Studio dependency must be free/open-
source and permit commercial use** (MIT / Apache-2.0 / BSD or similar). No paid
SDKs, no mandatory API keys/subscriptions, no watermarks, no vendor-hosted
services required for core functionality. Before adding any dependency, its
license is verified from the official source and recorded here.

## Editor engine decision
- **Approved:** Konva.js (MIT) as the rendering/editing engine.
- **Rejected — tldraw:** requires a **paid commercial license**; the SDK will
  not run in production without a purchased license key; pricing is sales-gated.
  Unsuitable under the free/commercial-use requirement.
- **Rejected — Polotno:** **paid** commercial SDK (~$899+). Unsuitable.
- (Full analysis and sources: `REPORT_STUDIO_REDESIGN.md` §4 / §4a.)

## Phase A dependencies (front-end, vendored locally — no CDN, no build)

| Library | Version | License | Commercial use | Source | Notes |
|---|---|---|---|---|---|
| Konva | 9.3.16 | **MIT** | Yes | github.com/konvajs/konva | Canvas rendering/editing engine |
| React | 18.3.1 | **MIT** | Yes | github.com/facebook/react | UI shell |
| ReactDOM | 18.3.1 | **MIT** | Yes | github.com/facebook/react | React DOM renderer |
| htm | 3.1.1 | **Apache-2.0** | Yes | github.com/developit/htm | JSX-like templates without a build step |

- All four are **vendored** into
  `src/fap/ui/builtin/frontend/report_studio/vendor/` (committed). They are
  obtained once (equivalent to an npm install) and served from our own component
  directory — **no runtime CDN**, no license key, no watermark, no vendor fee.
- **react-konva is NOT used.** It ships ESM-only (no UMD bundle) and requires a
  bundler, which this repo's component pipeline does not have. React drives the
  shell and Konva is driven directly (a standard React+Konva setup). react-konva
  (also MIT) may be adopted in a later phase if a Vite build is introduced; it
  would not change this licensing posture.

## Phase A dependencies (back-end)
- No new Python dependencies. The v2 adapter (`fap.reports.editor_adapter`) uses
  only the standard library and the existing `fap.reports.models`. Persistence
  reuses the existing `ReportsManager`.

## Policy for future phases
- Fonts: use system font stacks and/or **SIL OFL** / Apache-2.0 open fonts only.
- Icons: MIT/Apache/CC0 icon sets only (e.g. Lucide MIT), vendored.
- Charts: reuse the existing in-repo `fap.visuals` engine (no third-party paid
  chart SDK).
- PDF/PNG/JPG export: permissive libraries only (e.g. matplotlib/Pillow already
  in the app for server export; client export via the MIT Canvas API / jsPDF
  (MIT) if needed) — verified before adding.
- If any required capability cannot be met with free/OSS software, **stop and
  report** rather than introducing a paid dependency.
