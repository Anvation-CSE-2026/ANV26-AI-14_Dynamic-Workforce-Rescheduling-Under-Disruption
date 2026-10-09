// Hover-reasoning texts. Every sentence is assembled from numbers the solver or validator produced.
import type { Change, Fairness, Impact, Proposal, RepairOption, Rejected, Selected } from '../../api/types';
import { fmtDay } from '../../lib/format';

const n = (x: number, w: string) => `${x} ${w}${x === 1 ? '' : 's'}`;

export function whySelected(s: Selected | undefined, c: Change): string | undefined {
  if (!s) return undefined;
  const skills = s.matched_skills.length ? `the required ${s.matched_skills.join(', ')}` : 'every required skill';
  const rest = s.rest_hours_before_shift != null ? `, has ${s.rest_hours_before_shift}h rest before it` : '';
  const ot = s.overtime_hours_added ? `${s.overtime_hours_added}h of overtime` : 'no overtime';
  return `${s.employee_name} was selected because they have ${skills}, are available ${fmtDay(c.date)} ${c.start}–${c.end}${rest}, `
    + `and this takes their week from ${s.weekly_hours_before}h to ${s.weekly_hours_after}h `
    + `(contract ${s.contracted_weekly_hours}h, limit ${s.max_weekly_hours}h), creating ${ot}.`;
}

export function whyRemoved(p: Proposal, o: RepairOption, c: Change): string | undefined {
  if (!c.from_employee_name) return 'This shift had nobody assigned and must be covered.';
  const moved = o.changes.find((x) => x.to_employee_id === c.from_employee_id && x.shift_id !== c.shift_id);
  if (moved) return `${c.from_employee_name} moves to cover ${moved.assignment}; this shift is re-covered so nothing is left open.`;
  const item = p.problem?.items.find((i) => i.shift_ids.includes(c.shift_id));
  if (item) return `${item.title}: ${item.detail} (hard constraint: ${item.hard_constraint}).`;
  return `${c.from_employee_name} can no longer work this shift.`;
}

export function whyImpact(i: Impact): string {
  const untouched = i.horizon_shifts - i.assignments_changed;
  const head = i.unfilled_shifts
    ? `${n(i.assignments_changed, 'existing assignment')} changed and ${n(i.unfilled_shifts, 'shift')} left uncovered`
    : `Only ${n(i.assignments_changed, 'existing assignment')} changed while restoring full coverage`;
  return `${head}; ${untouched} of ${i.horizon_shifts} upcoming shifts are untouched. Score = 100 × (changes + 0.5·(affected − 1) `
    + `+ overtime/8 + 3·uncovered) / ${i.horizon_shifts} = ${i.impact_score}% (${i.impact_level}).`;
}

export function whyFairness(f: Fairness): string {
  return `Fairness reflects how evenly workload and recent disruptions are spread across employees: `
    + `${f.fairness_score} = 0.35×workload balance ${f.workload_balance} + 0.25×overtime spread ${f.overtime_distribution} `
    + `+ 0.25×change concentration ${f.change_concentration} + 0.15×preference respect ${f.preference_respect}.`;
}

export function whyRecommended(p: Proposal, o: RepairOption): string {
  const hard = p.result.hard_constraints?.length ?? 0;
  const base = `Recommended because it satisfies all ${hard || 'the'} hard constraints while minimizing schedule changes and overtime: `
    + `${n(o.impact.assignments_changed, 'change')}, ${n(o.impact.employees_affected, 'person')} affected, `
    + `${o.impact.overtime_hours_added}h overtime, fairness ${o.fairness.fairness_score}.`;
  return p.comparison?.headline ? `${base} ${p.comparison.headline}` : base;
}

const RULE_TEXT: Record<string, string> = {
  SHIFT_OVERLAP: 'This assignment would conflict with another shift assigned to the same employee',
  REST_PERIOD_VIOLATION: 'This would break the minimum-rest rule',
  MISSING_SKILL: 'Lacks a required skill',
  MISSING_CERTIFICATION: 'Lacks a required certification',
  UNAVAILABLE: 'Unavailable at that time',
  WOULD_CREATE_OVERTIME: 'Possible, but creates avoidable overtime',
  WOULD_EXCEED_MAX_HOURS: 'Would exceed a daily or weekly hours limit',
  WOULD_UNCOVER_SHIFT: 'Moving them would leave another shift uncovered',
  HIGHER_IMPACT: 'Valid, but changes more of the schedule than the recommendation',
  EXCLUDED_BY_MANAGER: 'Excluded by a manager instruction',
  LOCKED_BY_MANAGER: 'Their schedule is locked by a manager',
  MANAGER_FEEDBACK: 'Avoided because of earlier manager feedback',
  SCHEDULE_CONFLICT: 'Has to come off this shift because of a schedule conflict',
};

export function whyRejected(x: Rejected): string {
  const hard = ['SHIFT_OVERLAP', 'REST_PERIOD_VIOLATION', 'MISSING_SKILL', 'MISSING_CERTIFICATION', 'UNAVAILABLE',
    'WOULD_EXCEED_MAX_HOURS'].includes(x.reason_code);
  return `${RULE_TEXT[x.reason_code] ?? 'Ranked lower'}: ${x.detail}. `
    + (hard ? 'This is a hard constraint, so they cannot be selected.' : 'This is a soft trade-off; the solver measured it by re-solving with them forced in.');
}
