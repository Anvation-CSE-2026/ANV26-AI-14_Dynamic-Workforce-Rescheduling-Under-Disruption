// Types mirroring the backend JSON (see shared/schemas and docs/api-contract.md).

export type DomainId = 'healthcare' | 'manufacturing' | 'education' | 'technology' | 'logistics';
export type Role = 'admin' | 'operations_manager' | 'department_manager' | 'employee';

export interface User {
  id: string;
  name?: string | null;
  email?: string | null;
  role: Role;
  org?: string | null;
  employee_id?: string | null;
  must_change_password?: boolean;
  avatar?: string | null;
  phone?: string | null;
  status?: 'active' | 'inactive';
  created_at?: number;
  last_login?: number | null;
  notification_preferences?: NotificationPreferences;
}

/** Only two product roles are visible: Admin / Operations and Employee (legacy manager roles map to Admin). */
export const isAdmin = (role?: Role | null) => role === 'admin' || role === 'operations_manager' || role === 'department_manager';

export interface KpiDef {
  id: string;
  label: string;
  metric: string;
  format: 'percent' | 'count' | 'hours' | 'ratio';
  good: 'high' | 'low';
  hint: string;
}

export interface MetricValue {
  value?: number;
  total?: number;
  unit?: string;
  items?: string[];
}

export interface DomainSummary {
  id: DomainId;
  label: string;
  tagline: string;
  icon: string;
  accent: string;
  dashboardName: string;
}

export interface DomainConfig extends DomainSummary {
  identity: string;
  terminology: Record<string, string>;
  kpis: KpiDef[];
  commonKpis: KpiDef[];
  subDashboards: { id: string; name: string; audience: string; widgets: string[] }[];
  constraintLabels: Record<string, string>;
  riskIndicators: { id: string; label: string; metric: string }[];
  recommendedActions: string[];
  charts: string[];
}

export interface Preset {
  id: string;
  employee_id: string;
  date: string;
  start?: string | null;
  end?: string | null;
  reason?: string | null;
  severity: string;
  label?: string | null;
}

export interface WorkspaceSummary {
  org: string;
  organization: { id: string; name: string; domain: DomainId; location?: string; timezone: string; size?: string };
  domain: DomainId;
  source: string;
  version: string;
  loaded_at: string;
  reference_date?: string;
  reference_time?: string;
  counts: { employees: number; shifts: number; assignments: number; departments: number };
  presets: Preset[];
  config: DomainConfig;
}

export interface Finding {
  severity: 'error' | 'warning';
  category: string;
  path: string;
  message: string;
  record_id?: string | null;
}

export interface ValidationReport {
  status: 'valid' | 'valid_with_warnings' | 'invalid';
  errors: Finding[];
  warnings: Finding[];
  stats: Record<string, number>;
  summary: string;
}

export interface Contribution { date: string; kind: 'additional' | 'volunteer' | 'emergency' | 'reschedule' | 'overtime'; hours: number; completed: boolean; ref?: string | null }

export interface Employee {
  id: string;
  name: string;
  role: string;
  department?: string | null;
  email?: string | null;
  phone?: string | null;
  location?: string | null;
  status?: 'active' | 'inactive';
  max_daily_hours?: number;
  skills: string[];
  certifications: string[];
  contracted_weekly_hours: number;
  max_weekly_hours: number;
  history?: { disruptions_absorbed_30d: number; schedule_changes_30d: number; overtime_hours_30d: number; contributions?: Contribution[] };
  attributes: Record<string, unknown>;
}

export interface ScheduleRow {
  shift_id: string;
  date: string;
  start: string;
  end: string;
  hours: number;
  assignment: string;
  department?: string | null;
  shift_type?: string | null;
  priority: 'critical' | 'high' | 'normal';
  required_skills: string[];
  employee_id?: string | null;
  employee_name?: string | null;
  original_employee_id?: string | null;
  original_employee_name?: string | null;
  status: 'scheduled' | 'open' | 'disrupted' | 'changed';
  attributes: Record<string, unknown>;
}

export interface ScheduleConflict {
  id: string;
  type: 'double_booking' | 'rest_violation' | 'missing_skill' | 'missing_certification' | 'unavailable_assignee' | 'daily_hours' | 'weekly_hours' | 'open_shift';
  label: string;
  hard_constraint: string;
  employee_id?: string | null;
  employee_name?: string | null;
  shift_ids: string[];
  release: Record<string, string>;
  cover: string[];
  message: string;
  repairable: boolean;
  in_repair?: boolean;
}

export interface DisruptionRecord {
  id: string;
  kind?: 'absence' | 'conflict';
  status: 'open' | 'repaired' | 'dismissed';
  created_at: string;
  source: string;
  employee_name: string;
  affected_shifts: string[];
  disruption?: { id: string; employee_id: string; date: string; start?: string | null; end?: string | null; reason?: string | null; severity: string; label?: string | null };
  conflicts?: ScheduleConflict[];
  request_id?: string;
}

export interface Issue {
  code: string;
  message: string;
  field?: string | null;
  blocking: boolean;
  candidates: { id: string; name: string }[];
}

export interface Interpretation {
  status: 'READY' | 'NEEDS_CLARIFICATION' | 'UNSUPPORTED' | 'ERROR';
  issues: Issue[];
  assumptions: string[];
  confirmation_summary: string;
  confidence: { score: number; level: string; factors: string[] };
  unsupported_constraints: string[];
  meta: { prompt: string; provider: string };
}

export interface DisruptionResponse {
  status: Interpretation['status'];
  interpretation: Interpretation | null;
  disruptions: DisruptionRecord[];
}

export interface Impact {
  impact_score: number;
  impact_level: 'LOW' | 'MEDIUM' | 'HIGH';
  assignments_changed: number;
  employees_affected: number;
  overtime_hours_added: number;
  unfilled_shifts: number;
  horizon_shifts: number;
  preservation_rate: number;
  skill_coverage_pct: number;
  departments_affected: string[];
  formula: string;
}

export interface Fairness {
  fairness_score: number;
  workload_balance: number;
  overtime_distribution: number;
  change_concentration: number;
  preference_respect: number;
  preference_violations: number;
}

export interface Change {
  shift_id: string;
  date: string;
  start: string;
  end: string;
  assignment: string;
  department?: string | null;
  from_employee_id?: string | null;
  from_employee_name?: string | null;
  to_employee_id?: string | null;
  to_employee_name?: string | null;
  kind: 'reassigned' | 'uncovered' | 'filled';
}

export interface Selected {
  employee_id: string;
  employee_name: string;
  shift_id: string;
  covers: string;
  skills_match: boolean;
  matched_skills: string[];
  weekly_hours_before: number;
  weekly_hours_after: number;
  contracted_weekly_hours: number;
  max_weekly_hours: number;
  overtime_hours_added: number;
  rest_hours_before_shift?: number | null;
  previous_changes_30d: number;
  disruptions_absorbed_30d: number;
}

export interface RepairOption {
  option_id: string;
  label: string;
  title: string;
  strategy: string;
  goal: string;
  note?: string | null;
  status: string;
  assignment: Record<string, string | null>;
  changes: Change[];
  selected: Selected[];
  impact: Impact;
  fairness: Fairness;
  cost: number;
  cost_breakdown: Record<string, number>;
}

export interface Rejected {
  employee_id: string;
  employee_name: string;
  shift_id: string;
  reason_code: string;
  detail: string;
  extra_cost?: number | null;
}

export interface FunnelStep { stage: string; label: string; requirement: string; remaining: number; eliminated: { employee_id: string; name: string; detail: string }[] }
export interface UnresolvedShift {
  shift_id: string; date: string; start: string; end: string; assignment: string; department?: string | null; priority: string;
  required_skills: string[]; required_certifications: string[]; original_employee_name?: string | null; why_open: string;
  total_employees: number; funnel: FunnelStep[]; bottleneck?: string | null; bottleneck_label: string;
  blocking: { stage: string; label: string; eliminated: number; near_misses: { employee_id: string; name: string; detail: string }[] }[];
  resolutions: { action: string; detail: string; kind: 'operational' | 'manual_override' }[];
  summary: string;
}
export interface ConstraintItem { id: string; label: string; detail: string; kind?: string; weight?: number }

export interface ExplanationPoint { text: string; fact_refs: string[] }
export interface Explanation {
  headline: string;
  points: ExplanationPoint[];
  why_not_others: ExplanationPoint[];
  source: 'llm' | 'template';
  grounding_warnings: string[];
}

export interface PolicyConstraintView {
  type: string;
  value: number | boolean | string;
  unit?: string | null;
  severity: 'hard' | 'soft';
  scope: string;
  source: string;
  policy_id: string;
  quote: string;
  enforced?: boolean;
  confidence: number;
}

export interface Proposal {
  id: string;
  status: 'pending' | 'approved' | 'rejected';
  created_at: string;
  parent_id?: string | null;
  scenario?: string | null;
  run_notes: string[];
  priority?: string | null;
  relaxation?: { change: string; message: string } | null;
  approved_option?: string;
  result: {
    status: 'OPTIMAL' | 'FEASIBLE' | 'PARTIAL' | 'INFEASIBLE';
    disruptions: { id: string; employee_id: string; date: string; start?: string | null; end?: string | null; reason?: string | null }[];
    solver: string;
    solve_ms: number;
    disrupted_shifts: string[];
    options: RepairOption[];
    recommended_option_id?: string | null;
    rejected: Rejected[];
    baseline?: { method: string; assignments_changed: number; employees_affected: number; uncovered: number } | null;
    infeasibility_reasons: string[];
    unresolved?: UnresolvedShift[];
    hard_constraints?: ConstraintItem[];
    soft_objectives?: ConstraintItem[];
    constraints_used: Record<string, unknown>;
  };
  problem?: { items: { kind: string; title: string; detail: string; hard_constraint: string; shift_ids: string[] }[];
              affected_shifts: { shift_id: string; assignment: string; date: string; start: string; end: string; priority: string }[] };
  comparison?: { headline: string; points: ExplanationPoint[]; recommended_id?: string; best_by: Record<string, string[]>; dominated: Record<string, string>; non_compliant: Record<string, string> } | null;
  explanations: Record<string, Explanation>;
  policy: { mode: string; constraints: PolicyConstraintView[]; conflicts: string[]; warnings: string[]; topics_without_policy: string[] };
}

export interface WhatIfResponse {
  status: string;
  scenario: { status: string; summary: string; issues: Issue[]; unsupported: string[] };
  proposal?: Proposal;
  delta?: { comparable: boolean; message?: string; delta?: Record<string, number>; before?: { label: string; impact: Impact; fairness: Fairness }; after?: { label: string; impact: Impact; fairness: Fairness } };
}

export type Severity = 1 | 2 | 3;
export interface ChannelDelivery {
  channel: 'dashboard' | 'email' | 'whatsapp' | 'sms';
  status: 'sent' | 'delivered' | 'opened' | 'failed' | 'skipped' | 'opted_out';
  provider?: string | null; sent_at?: string | null; delivered_at?: string | null; opened_at?: string | null;
  acknowledged_at?: string | null; escalation_level: number; error?: string | null;
}
export interface NotificationPreferences { email?: boolean; sms?: boolean; whatsapp?: boolean }

export interface Notification {
  id: string;
  employee_id: string;
  employee_name?: string;
  title: string;
  body: string;
  message?: string;
  severity?: Severity;
  level?: 'informational' | 'important' | 'critical';
  color?: 'green' | 'orange' | 'red';
  type?: string;
  status?: 'sent' | 'delivered' | 'opened' | 'acknowledged' | 'escalated';
  channels?: ChannelDelivery[];
  escalation_level?: number;
  escalated_at?: string | null;
  opened_at?: string | null;
  admin_request_id?: string;
  workforce_request_id?: string;
  kind?: string;
  changes?: { change_type: string; date: string; from_assignment?: string | null; to_assignment?: string | null; from_shift?: string | null; to_shift?: string | null }[];
  requires_acknowledgement: boolean;
  acknowledged_at?: string | null;
  version?: string;
  created_at: string;
  voice_text?: string;
}

export interface Version {
  id: string;
  tag: string;
  parent?: string | null;
  created_at: string;
  created_by: string;
  title: string;
  status: 'active' | 'superseded';
  changes: Change[];
  impact?: Impact;
  fairness?: Fairness;
  notes?: string;
  policies?: string[];
}

export interface AuditEvent {
  id: string; event_type: string; actor: string; description: string; timestamp: string; details: Record<string, unknown>;
  previous?: unknown; new?: unknown; reason?: string | null;
}

export interface Dashboard {
  domain: DomainId;
  dashboardName: string;
  organization: WorkspaceSummary['organization'];
  version: string;
  metrics: Record<string, MetricValue>;
  kpis: (KpiDef & { value: MetricValue })[];
  commonKpis: (KpiDef & { value: MetricValue })[];
  widgets: WidgetData;
  open_disruptions: DisruptionRecord[];
  latest_proposal?: { id: string; status: string; created_at: string; solver: string; options: number; result_status: string; feasible: boolean;
                      unresolved: { assignment: string; date: string; summary: string }[]; problem: string[];
                      recommended?: { label: string; title: string; impact: Impact; fairness: Fairness } } | null;
  pending_requests: EmployeeRequest[];
  conflicts: ScheduleConflict[];
  overview?: AdminOverview;
}

export interface WidgetData {
  department_coverage?: { department: string; covered: number; total: number; at_risk: number }[];
  qualification_matrix?: { skill: string; demand: number; holders: number }[];
  fatigue_risk?: { employee_id: string; employee: string; reason: string }[];
  overtime_by_person?: { employee_id: string; employee: string; hours: number; contracted: number; overtime: number }[];
  workload_balance?: { employee: string; hours: number }[];
  fairness_distribution?: { employee: string; disruptions_absorbed_30d: number; schedule_changes_30d: number; overtime_hours_30d: number }[];
  disruption_history?: { date: string; employee: string; status: string; reason?: string | null; source: string }[];
}

export interface Analytics {
  conflicts_detected?: number;
  conflicts_resolved?: number;
  avg_repair_minutes?: number | null;
  avg_solve_ms?: number | null;
  staffing_gaps?: number;
  staffing_gap_people?: number;
  workforce?: WorkforceSummary;
  volunteer_participation?: number;
  hard_constraint_rejections?: number;
  hard_constraint_violations_published?: number;
  soft_constraint_satisfaction?: number | null;
  fairness_distribution?: { employee: string; load: number; weekly_hours: number }[];
  fairness_spread?: number;
  rewards_issued?: number;
  reward_points?: number;
  notifications?: NotificationSummary;
  workload_distribution?: { employee: string; hours: number }[];
  rewards_by_trigger?: { trigger: string; count: number }[];
  pending_rewards?: number;
  disruptions: number;
  repairs_approved: number;
  repair_success_rate: number | null;
  avg_impact_score: number | null;
  avg_employees_affected: number | null;
  overtime_hours_avoided: number;
  assignment_changes_avoided_vs_rebuild: number;
  skill_coverage_pct: number;
  avg_fairness_score: number | null;
  schedule_stability_pct: number;
  most_common_disruption: string | null;
  most_affected_department: string | null;
  versions: number;
  trend: { date: string; disruptions: number; repairs: number }[];
  repair_impact: { version: string; impact: number; changes: number; overtime: number; fairness: number }[];
  disruption_reasons: { reason: string; count: number }[];
}

export interface PolicyOverview {
  documents: { policy_id: string; title: string; version: string; effective_date?: string; chunks: number }[];
  mode: string;
  constraints: PolicyConstraintView[];
  conflicts: string[];
  unsupported: string[];
}

export interface PolicySearch {
  query: string;
  status: 'found' | 'no_applicable_policy';
  message: string;
  hits: { citation: string; policy_id: string; section: string; text: string; confidence: number }[];
}

export type RequestStatus = 'pending' | 'approved' | 'rejected' | 'needs_review' | 'completed';
export type RequestKind = 'unavailable' | 'time_off' | 'shift_swap' | 'preference';
export interface EmployeeRequest {
  id: string; employee_id: string; employee_name: string; date: string; start?: string | null; end?: string | null;
  reason: string; kind: RequestKind; status: RequestStatus; created_at: string; updated_at?: string;
  affected_shifts?: string[]; manager_note?: string | null; decided_by?: string | null; disruption_id?: string | null;
  history?: { status: RequestStatus; at: string; by: string; note?: string | null }[];
}

export interface EmployeeView {
  employee: Employee;
  schedule: ScheduleRow[];
  notifications: Notification[];
  requests: EmployeeRequest[];
}

export interface RecognitionCategory { id: string; label: string; description: string; signals: string[]; points: number; managerAwardable: boolean }
export interface RecognitionTier { points: number; label: string; benefit: string }
export interface Award { id: string; employee_id: string; employee_name: string; category: string; category_label: string; signal: string; points: number; source: 'system' | 'manager' | 'reward'; reason: string; awarded_by: string; created_at: string; badge?: string | null }
export interface RecognitionSummary {
  employee_id: string; employee_name: string; points_90d: number; tier: RecognitionTier | null; next_tier: RecognitionTier | null;
  categories: { category: string; label: string; count: number; points: number }[]; awards: Award[];
}
export interface RecognitionConfig { categories: RecognitionCategory[]; tiers: RecognitionTier[] }

export interface DemoAccount { email: string; password: string; role: Role; name: string; domain: DomainId | 'flagship'; org: string; title: string; story?: string | null }

export interface VoiceReply {
  intent: string;
  text: string;
  action?: unknown;
  audio?: { mime: string; base64: string } | null;
  transcript?: string;
  understood_by?: string;
  navigate?: { screen: string; proposal_id?: string } | null;
}


// ===================================================================== operations (Admin / Employee)

export interface SolverStatus {
  engine: string; cp_sat: boolean; installed: boolean; version: string | null;
  self_test: { ok: boolean; status: string; ms: number } | null; message: string;
}

export interface FairnessProfile {
  employee_id: string; employee_name: string; window_days: number; regular_hours: number; weekly_hours: number;
  monthly_hours: number; contracted_weekly_hours: number; overtime_hours: number; additional_assignments: number;
  volunteer_assignments: number; completed_volunteer_assignments: number; emergency_coverage: number;
  recent_reschedules: number; recent_additional_hours: number; last_additional_assignment: string | null;
  last_emergency_assignment: string | null; contribution_load: number; older_contributions: number;
}

export interface RepairCenterRow {
  id: string; status: 'pending' | 'approved' | 'rejected'; state: 'pending' | 'approved' | 'completed' | 'rejected';
  hidden: boolean; created_at: string; decided_at?: string | null; decided_by?: string | null; what_if: boolean;
  parent_id?: string | null; problem: string[]; affected_shifts: number; critical: boolean; solver: string;
  result_status: string; options: number; unresolved: number; completed_at?: string | null; pending_completion: number;
  recommended: { label: string; title: string; changes: number; employees_affected: number; overtime: number;
                 impact: number; impact_level: Impact['impact_level']; fairness: number } | null;
}
export interface RepairCenter {
  repairs: RepairCenterRow[];
  counts: Record<'pending' | 'approved' | 'completed' | 'rejected' | 'hidden' | 'active_disruptions' | 'critical_disruptions', number>;
  active_disruptions: DisruptionRecord[];
  critical_disruption_ids: string[];
}

export type SimulationAction =
  | { type: 'assign' | 'accept_volunteer'; shift_id: string; employee_id: string }
  | { type: 'option'; option_id: string }
  | { type: 'move_shift'; shift_id: string; start: string; end: string }
  | { type: 'add_employee'; skills?: string[] };
export interface Simulation {
  type: string; feasible: boolean; conflicts_introduced: string[]; constraints_affected: string[];
  changes: { shift_id: string; assignment: string; date: string; start: string; end: string; from?: string | null; to?: string | null;
             from_employee_name?: string | null; to_employee_name?: string | null }[];
  changes_count: number; workload: { employee_id: string; employee_name: string; before: number; after: number }[];
  fairness_before: number | null; fairness_after: number | null; overtime_added: number; impact: number | null;
  optimization_score: number | null; baseline_score: number | null; summary: string; saved: false;
}

export interface Check { name: string; status: 'pass' | 'fail'; detail: string; kind: 'hard' | 'soft' }
export interface SoftNote { label: string; status: 'good' | 'warn'; detail: string }
export interface Candidate {
  employee_id: string; employee_name: string; role: string; department?: string | null; eligible: boolean;
  checks: Check[]; failed: Check | null; weekly_hours_before: number; weekly_hours_after: number; overtime_added: number;
  location_match: boolean; preference_ok: boolean; score?: number; rank?: number; soft?: SoftNote[];
  fairness: Pick<FairnessProfile, 'contribution_load' | 'volunteer_assignments' | 'additional_assignments' | 'emergency_coverage'
    | 'weekly_hours' | 'monthly_hours' | 'last_additional_assignment' | 'window_days'>;
}
export interface CandidateSearch {
  shift: { date: string; start: string; end: string; task: string; skills: string[]; certifications: string[] };
  eligible: Candidate[]; ineligible: Candidate[]; funnel: { stage: string; remaining: number }[];
  needed: number; sufficient: boolean; message: string | null;
}

export interface AssistantConflict {
  id: string; type: string; type_label: string; severity: 'critical' | 'high' | 'medium' | 'low';
  employee_id?: string | null; employee_name?: string | null; task: string; shift_id: string; date: string; start: string;
  end: string; priority: string; impact: { shifts: number; hours: number; starts_in_hours: number; critical: boolean };
  why: string; constraints: string[]; recommendation: string;
  recommended: { employee_id: string; employee_name: string; checks: { label: string; status: string }[]; soft: SoftNote[];
                 fairness: Candidate['fairness'] } | null;
  alternatives: ({ kind: 'employee'; employee_id: string; employee_name: string; rank: number; tradeoffs: string[] }
                 | { kind: 'split_shift' | 'workforce_request' | 'volunteers'; label: string })[];
  confidence: 'high' | 'medium' | 'low'; eligible_count: number; funnel: { stage: string; remaining: number }[];
  rejected: { employee_name: string; reason: string; detail: string }[];
  explanation: string; strategies: string[]; explained_by: string; ai_discarded: string[];
  policy: { citation: string; text: string; confidence: number } | null;
  disruption_id?: string | null; conflict_id?: string | null; gap?: StaffingGap | null;
}
export interface ConflictAssistant { conflicts: AssistantConflict[]; count: number; critical: number; llm: string | null; policies_used: number; note: string }

export interface StaffingGap {
  id: string; task: string; date: string; start: string; end: string; department?: string | null; location?: string | null;
  skills: string[]; certifications: string[]; required: number; assigned: number; gap: number; assigned_ids: string[];
  priority: 'critical' | 'high' | 'normal'; shift_ids: string[];
}
export interface WorkforceForm {
  task: string; date: string; start: string; end: string; required_employees?: number; additional_needed: number;
  department?: string; skills: string[]; certifications: string[]; location?: string; priority: 'critical' | 'high' | 'normal';
  reason: string; emergency?: boolean; gap_id?: string;
}
export interface Volunteer { employee_id: string; employee_name: string; at: string; status: 'volunteered' | 'declined' | 'approved' | 'not_selected'; eligible: boolean; validation: string; rank?: number | null }
export interface WorkforceAssignment { employee_id: string; employee_name: string; shift_id: string; status: 'assigned' | 'completed'; assigned_at: string; completed_at?: string | null; volunteer: boolean; rank?: number | null; eligibility_id?: string }
export interface WorkforceRequest extends Omit<WorkforceForm, 'department' | 'location'> {
  id: string; department?: string | null; location?: string | null; status: 'open' | 'partially_filled' | 'filled' | 'cancelled';
  created_by: string; created_at: string; updated_at: string; invited: string[]; volunteers: Volunteer[];
  assignments: WorkforceAssignment[]; eligible_count: number; sufficient: boolean; message: string | null;
  history: { at: string; by: string; event: string }[]; candidates?: CandidateSearch;
}
export interface WorkforceSummary { open: number; filled: number; volunteers: number; assigned: number; completed: number }

export type AdminRequestType = 'task' | 'shift_coverage' | 'availability_confirmation' | 'training' | 'schedule_confirmation'
  | 'general' | 'emergency_coverage' | 'volunteer_opportunity';
export type RequestAction = 'accept' | 'decline' | 'acknowledge';
export interface AdminRequest {
  id: string; type: AdminRequestType; title: string; message: string; severity: Severity;
  target: { kind: 'employee' | 'employees' | 'department' | 'role' | 'eligible'; value: unknown };
  actions: RequestAction[]; workforce_request_id?: string | null; due?: string | null; status: 'open' | 'completed' | 'closed';
  created_by: string; created_at: string; updated_at: string;
  recipients?: { employee_id: string; employee_name: string; status: 'pending' | 'accepted' | 'declined' | 'acknowledged'; responded_at: string | null; note: string | null }[];
  my_status?: 'pending' | 'accepted' | 'declined' | 'acknowledged'; responded_at?: string | null; recipient_count?: number;
}

export interface NotificationSummary {
  total: number; by_level: Record<string, number>; awaiting_acknowledgement: number; acknowledged: number; escalated: number;
  providers: Record<string, string>;
}
export interface NotificationAuditRow {
  notification_id: string; employee_id: string; employee_name?: string | null; severity: Severity; type: string; message: string;
  channel: string; provider?: string | null; created_at: string; sent_at?: string | null; delivered_at?: string | null;
  opened_at?: string | null; acknowledged_at?: string | null; status: string; escalation_level: number;
}
export interface NotificationSettings {
  l2_escalation_minutes: number; providers: Record<string, string>;
  levels: Record<string, { name: string; label: string; color: string; channels: string[]; escalation: string[] }>;
  future_channels: string[];
}

export interface Badge { id: string; name: string; description: string; icon: string; count?: number; first_earned?: string }
export interface Achievement { id: string; name: string; metric: string; target: number; progress: number; unlocked: boolean }
export interface RewardRule { id: string; trigger: string; label: string; category?: string | null; points: number; badge?: string | null; requires_approval: boolean; enabled: boolean }
export interface RewardEligibility {
  id: string; employee_id: string; employee_name: string; trigger: string; ref: string; shift_id: string; date: string; end: string;
  task: string; source: string; source_id?: string | null; status: 'pending_completion' | 'pending_approval' | 'rewarded' | 'completed' | 'completed_no_reward';
  created_at: string; completed_at?: string | null; points: number;
}
export interface RewardConfig { rules: RewardRule[]; badges: Badge[]; achievements: Omit<Achievement, 'progress' | 'unlocked'>[] }
export interface EmployeeRewards extends RecognitionSummary {
  config: RewardConfig; points_total: number; badges: Badge[]; achievements: Achievement[]; history: Award[];
  contributions: RewardEligibility[]; pending: RewardEligibility[];
}
export interface RewardsOverview {
  config: RecognitionConfig & RewardConfig; triggers: Record<string, string>;
  employees: (Pick<EmployeeRewards, 'employee_id' | 'employee_name' | 'points_90d' | 'points_total' | 'tier' | 'next_tier' | 'categories' | 'badges' | 'achievements'>)[];
  recent: Award[]; pending_approval: RewardEligibility[]; pending_completion: RewardEligibility[];
  stats: { points_30d: number; rewards_issued: number; badges_issued: number; awaiting_completion: number };
}

export interface ConstraintRow {
  constraint_id: string; type: 'HARD' | 'SOFT'; category: string; rule: string; priority: 'HIGH' | 'MEDIUM' | 'LOW';
  weight: number; enabled: boolean; locked: boolean; value: number | string | string[] | null; unit: string | null;
  scope: Record<string, string> | null; enforced: boolean; source: 'built-in' | 'imported';
}
export interface ConstraintCatalog { constraints: ConstraintRow[]; hard_categories: string[]; soft_categories: string[]; solver: SolverStatus }
export interface ConstraintImport { valid: ConstraintRow[]; errors: string[]; applied: boolean; unenforced: string[]; changes?: { constraint_id: string; field: string; previous: unknown; new: unknown }[] }
export interface ConstraintTest {
  checked_at: string; assignments: number;
  results: { constraint_id: string; category: string; type: 'HARD' | 'SOFT'; enabled: boolean; enforced: boolean; status: 'pass' | 'fail' | 'skipped' | 'info'; violations: number; message: string }[];
  summary: { fail: number; pass: number };
}

export interface ImportRow { row: number; status: 'valid' | 'invalid' | 'duplicate' | 'existing'; errors: string[]; warnings: string[]; data: Record<string, unknown>; hard_warning?: boolean }
export interface ImportReport { rows: ImportRow[]; total: number; valid: number; invalid: number; duplicates: number; existing: number; warnings: number }
export interface ImportJob { id: string; kind: 'employees' | 'schedule'; filename: string; status: 'preview' | 'confirmed'; created_at: string; report: ImportReport }
export interface EmployeeImportResult { created: Employee[]; accounts: number; skipped_accounts: { employee_id: string; reason: string }[]; credentials_token: string; expires_in_s: number; report: ImportReport }

export interface DirectoryEmployee extends Employee { shifts: number; fairness: FairnessProfile; login?: string | null }

export interface ProfileData {
  user: User; role_label: string; organization: WorkspaceSummary['organization'] | null;
  sessions: { sid: string; created_at: number; last_seen: number; user_agent: string; current: boolean }[];
  employee: (Employee & { points: number; points_90d: number; tier: RecognitionTier | null; badges: Badge[];
                          availability: { date: string; start?: string | null; end?: string | null; kind: string; reason?: string | null }[] }) | null;
}

export interface EmployeeHome extends EmployeeView {
  today: string; now?: string | null; today_shifts: ScheduleRow[]; next_shift: ScheduleRow | null; upcoming: ScheduleRow[];
  conflict_alerts: ScheduleRow[];
  opportunities: { id: string; task: string; date: string; start: string; end: string; location?: string | null; skills: string[];
                   priority: string; emergency: boolean; my_status: Volunteer['status'] | null }[];
  admin_requests: AdminRequest[]; rewards: EmployeeRewards; workload: FairnessProfile;
}

export interface AdminOverview {
  staffing_gaps: StaffingGap[]; workforce: WorkforceSummary; notifications: NotificationSummary;
  repairs: RepairCenter['counts']; fairness: FairnessProfile[];
  rewards: RewardsOverview['stats']; employees: { active: number; inactive: number }; solver: SolverStatus;
}
