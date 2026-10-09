# Domains: one engine, five industries

Industry behaviour is configuration. `shared/domains/<id>.json` is produced by `backend/scripts/build_domain_configs.py` and served by `GET /api/domains/{id}`. The UI reads it through `DomainProvider` (`frontend/src/lib/domain.tsx`), so labels, KPIs and dashboards change without any code changes.

```jsonc
{
  "id": "healthcare", "label": "Healthcare", "icon": "HeartPulse", "accent": "#0f766e",
  "dashboardName": "Hospital Command Center",
  "terminology": {"employee": "Staff member", "department": "Unit", "shift": "Shift", "skills": "Certifications", …},
  "kpis": [{"id": "staff_coverage", "label": "Staff Coverage", "metric": "coverage_pct", "format": "percent", "good": "high", "hint": "…"}],
  "commonKpis": [ … workforce status, schedule coverage, active disruptions, at-risk assignments, overtime, skill coverage … ],
  "subDashboards": [
    {"id": "clinical", "name": "Clinical Staff Dashboard", "audience": "Charge nurses & unit leads",
     "widgets": ["department_coverage", "roster", "qualification_matrix", "fatigue_risk"]},
    {"id": "hr", "name": "Hospital Workforce / HR Dashboard", "audience": "…", "widgets": ["overtime_by_person", "fairness_distribution", "disruption_history", "compliance"]}
  ],
  "constraintLabels": {"min_rest_hours": "Minimum rest between shifts", …},
  "riskIndicators": [{"id": "fatigue", "label": "Fatigue risk", "metric": "fatigue_risk_count"}],
  "recommendedActions": ["Confirm the replacement with the charge nurse", …]
}
```

KPIs point at **metric keys** computed generically by `services/kpis.py`: `coverage_pct, at_risk_assignments, uncovered_shifts, critical_uncovered, at_risk_departments, available_staff, active_disruptions, overtime_hours, skill_coverage_pct, skill_gap_count, avg_weekly_hours, schedule_conflicts, oncall_coverage_pct, deadline_risk, route_risk, fatigue_risk_count`.

Widgets are generic components (`frontend/src/components/widgets/Widgets.tsx`): `department_coverage, roster, qualification_matrix, fatigue_risk, overtime_by_person, workload_balance, fairness_distribution, disruption_history, compliance`.

## The five configurations

| | Healthcare | Manufacturing | Education | Technology | Logistics |
|---|---|---|---|---|---|
| Command center | Hospital Command Center | Plant Operations Command Center | Academic Operations Dashboard | Technology Workforce Command Center | Field Operations Command Center |
| Sub-dashboards | Clinical Staff · Hospital Workforce / HR | Shift Supervisor · Workforce / HR | Teacher / Department · Academic Admin | Engineering Manager · Resource Management | Dispatch · Resource Management |
| KPIs | Staff coverage, critical shortages, skill coverage, overtime, at-risk units | Production coverage, at-risk lines, skill gaps, overtime, operator availability | Teacher coverage, class coverage, subject gaps, workload, conflicts | Project coverage, skill gaps, developer capacity, on-call coverage, deadline risk | Assignment coverage, route risk, driver availability, certification coverage, overtime |
| Person / unit | Staff member / Unit | Operator / Line | Teacher / Department | Engineer / Team | Driver / Depot |
| Policy handbook | Nursing Working Time & Staffing | Plant Shift & Safety | Teacher Workload | Engineering Capacity & On-call | Driver Hours |
| Demo org | St. Aster Multispeciality Hospital | Vega Precision Components | Greenfield Public School | Nimbus Pay | SwiftRoute Logistics |

## Adding an industry

1. Add the id to `DOMAINS` in `core/models.py`.
2. Add its config to `scripts/build_domain_configs.py` (or write `shared/domains/<id>.json` by hand) and list it in `index.json`.
3. Add a policy handbook under `shared/policies/<id>/`.
4. Add a demo dataset (`scripts/build_demo_datasets.py`) with a couple of `disruptions` presets.

No engine, API or UI code changes are needed.

The UI icon comes from `icon`. Names not mapped in `frontend/src/components/common/DomainIcon.tsx` fall back to a generic building icon.
