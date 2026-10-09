# ResQWork frontend

React 19 + Vite + Tailwind CSS v4. All data comes from the FastAPI backend through `src/api/client.ts`; there are no mocks.

```bash
npm install
npm run dev        # http://localhost:3000, proxies /api → http://localhost:8000
npm run build      # dist/ (FastAPI serves it automatically when present)
```

Environment (`.env`, public values only): `VITE_API_URL` (leave empty to use the proxy), `VITE_GOOGLE_CLIENT_ID` (optional Google sign-in).

## Structure

```
src/
  api/          client.ts (typed fetch wrappers), types.ts (mirrors backend JSON)
  lib/          domain.tsx (DomainProvider + terminology), toast.tsx, speech.ts (Web Speech API), format.ts
  components/
    common/     Button, Card, Modal, Tabs, MetricCard, Badge, States (loading/empty/error), DomainIcon
    charts/     dependency-free bar lists, stacked bars, gauges, trend bars
    widgets/    generic dashboard widgets chosen per industry by shared/domains/*.json
    layout/     Shell (sidebar + header)
    voice/      VoiceAgent panel (speech in/out, always with text fallback)
  screens/      Landing, Onboarding, Dashboard, SubDashboard, Schedule, Repair, Policies,
                Versions, Analytics, EmployeePortal
```

## Domain adaptivity

`DomainProvider` receives the workspace's domain config. Screens use `t('employee')`, `config.kpis`, `config.subDashboards[i].widgets`, `config.constraintLabels` and so on, so no screen hard-codes an industry.

## Accessibility

Labelled form controls, `aria-live` toasts and voice transcript, keyboard-reachable controls with visible focus rings, text equivalents for every chart, reduced-motion support, and voice that always has a text fallback.
