// ResQWork API client: typed wrappers over the FastAPI backend. No business logic here.
//
// Robust by design: never calls JSON.parse blindly. It checks the content type, handles empty bodies,
// HTML error pages (e.g. a proxy or the SPA fallback), network failures, timeouts, validation errors and
// auth failures, and always throws an ApiError with a message a person can act on.

import type {
  AdminRequest, AdminRequestType, Analytics, AuditEvent, Award, CandidateSearch, ConflictAssistant, ConstraintCatalog,
  ConstraintImport, ConstraintRow, ConstraintTest, Dashboard, DemoAccount, DirectoryEmployee, DisruptionRecord,
  DisruptionResponse, DomainConfig, DomainId, DomainSummary, Employee, EmployeeHome, EmployeeImportResult, EmployeeRequest,
  EmployeeRewards, EmployeeView, FairnessProfile, ImportJob, Notification, NotificationAuditRow, NotificationSettings,
  NotificationSummary, PolicyOverview, PolicySearch, ProfileData, Proposal, RecognitionConfig, RecognitionSummary,
  RepairCenter, RequestAction, RewardConfig, RewardEligibility, RewardRule, RewardsOverview, Role, ScheduleConflict,
  ScheduleRow, Simulation, SimulationAction, SolverStatus, StaffingGap, User, ValidationReport, Version, VoiceReply,
  WhatIfResponse, WorkforceForm, WorkforceRequest, WorkspaceSummary,
} from './types';

const BASE: string = import.meta.env.VITE_API_URL ?? '';
const TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS ?? '') || 45000;
const TOKEN_KEY = 'resqwork.token';

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public fields?: { field: string; message: string }[]) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Human message for anything thrown (ApiError, Error, string, unknown). */
export function errorMessage(e: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (e instanceof Error && e.message) return e.message;
  if (typeof e === 'string' && e) return e;
  return fallback;
}

let token: string | null = (() => {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
})();

export function setToken(t: string | null) {
  token = t;
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* storage unavailable (private window): keep the in-memory token */ }
}

export const hasToken = () => !!token;

/** App-level listeners: the shell signs out on 401 and shows the password screen on PASSWORD_CHANGE_REQUIRED. */
type AuthListener = (kind: 'unauthorized' | 'password_change_required') => void;
const authListeners = new Set<AuthListener>();
export function onAuthEvent(fn: AuthListener): () => void {
  authListeners.add(fn);
  return () => { authListeners.delete(fn); };
}

const STATUS_TEXT: Record<number, string> = {
  400: 'The request was not valid.', 401: 'Please sign in again.', 403: 'You don’t have access to this.',
  404: 'Not found.', 408: 'The server took too long to respond.', 409: 'This conflicts with the current state. Refresh and try again.',
  413: 'The file is too large.', 422: 'Some fields are invalid.', 429: 'Too many requests. Wait a moment and try again.',
  500: 'Something went wrong on the server.', 502: 'The server is unavailable (bad gateway).', 503: 'The service is temporarily unavailable.',
  504: 'The server took too long to respond.',
};

interface ErrorBody { error?: string; code?: string; detail?: unknown; fields?: { field: string; message: string }[] }

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function messageFrom(body: unknown, status: number): { message: string; code?: string; fields?: ErrorBody['fields'] } {
  if (isRecord(body)) {
    const b = body as ErrorBody;
    if (typeof b.error === 'string' && b.error) return { message: b.error, code: b.code, fields: b.fields };
    if (typeof b.detail === 'string') return { message: b.detail };
    if (Array.isArray(b.detail)) {
      const parts = b.detail.map((d) => (isRecord(d) && typeof d.msg === 'string' ? d.msg : '')).filter(Boolean);
      if (parts.length) return { message: parts.join('; ') };
    }
  }
  return { message: STATUS_TEXT[status] ?? `Request failed (${status}).` };
}

type Body = { kind: 'json'; value: unknown } | { kind: 'form'; value: FormData } | { kind: 'none' };

async function send(method: string, path: string, body: Body, timeoutMs: number): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body.kind === 'json') headers['Content-Type'] = 'application/json';
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(`${BASE}${path}`, {
      method, headers, signal: ctrl.signal,
      body: body.kind === 'json' ? JSON.stringify(body.value) : body.kind === 'form' ? body.value : undefined,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError('The server took too long to respond. Please try again.', 408);
    }
    throw new ApiError('Can’t reach the ResQWork server. Check that it is running and you are online.', 0);
  } finally {
    clearTimeout(timer);
  }
}

async function readBody(res: Response): Promise<unknown> {
  if (res.status === 204 || res.status === 205) return null;
  const type = res.headers.get('content-type') ?? '';
  const text = await res.text();
  if (!text.trim()) return null;
  if (type.includes('application/json') || type.includes('+json')) {
    try { return JSON.parse(text) as unknown; } catch { throw new ApiError('The server sent a malformed response.', res.status || 502); }
  }
  if (type.includes('text/html') || /^\s*<(!doctype|html)/i.test(text)) {
    // An HTML page where JSON was expected: a proxy error page or an unknown route served by the SPA.
    throw new ApiError(res.ok ? 'The server returned a web page instead of data. Is the API URL correct?'
      : (STATUS_TEXT[res.status] ?? `Request failed (${res.status}).`), res.ok ? 502 : res.status);
  }
  return text;
}

function fail(res: Response, body: unknown): never {
  const { message, code, fields } = messageFrom(body, res.status);
  if (res.status === 401) authListeners.forEach((fn) => fn('unauthorized'));
  if (code === 'PASSWORD_CHANGE_REQUIRED') authListeners.forEach((fn) => fn('password_change_required'));
  throw new ApiError(message, res.status, code, fields);
}

async function request<T>(method: string, path: string, body: Body = { kind: 'none' }, timeoutMs = TIMEOUT_MS): Promise<T> {
  const res = await send(method, path, body, timeoutMs);
  let data: unknown;
  try {
    data = await readBody(res);
  } catch (e) {
    if (!res.ok && e instanceof ApiError) fail(res, null);
    throw e;
  }
  if (!res.ok) fail(res, data);
  return data as T;
}

/** Download a file (blob) and hand it to the browser. Errors are parsed the same way as JSON calls. */
async function download(method: 'GET' | 'POST', path: string, fallbackName: string): Promise<void> {
  const res = await send(method, path, method === 'POST' ? { kind: 'json', value: {} } : { kind: 'none' }, TIMEOUT_MS);
  if (!res.ok) fail(res, await readBody(res).catch(() => null));
  const blob = await res.blob();
  const cd = res.headers.get('content-disposition') ?? '';
  const name = /filename="?([^";]+)"?/i.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const get = <T,>(p: string) => request<T>('GET', p);
const post = <T,>(p: string, b: unknown = {}, timeoutMs?: number) => request<T>('POST', p, { kind: 'json', value: b }, timeoutMs);
const put = <T,>(p: string, b: unknown) => request<T>('PUT', p, { kind: 'json', value: b });
const patch = <T,>(p: string, b: unknown) => request<T>('PATCH', p, { kind: 'json', value: b });
const del = <T,>(p: string) => request<T>('DELETE', p);
const upload = <T,>(p: string, form: FormData) => request<T>('POST', p, { kind: 'form', value: form }, 120000);
const fileForm = (file: File, extra: Record<string, string> = {}) => {
  const f = new FormData();
  f.append('file', file);
  Object.entries(extra).forEach(([k, v]) => f.append(k, v));
  return f;
};
const SOLVE_TIMEOUT = 120000;   // repairs on large organizations can take a while

export interface Me extends User { must_change_password?: boolean }
/** The command box routes one message to a disruption, a what-if, feedback or a policy lookup. */
export interface InterpretPayload extends Partial<Omit<DisruptionResponse, 'status'>>, Partial<Omit<WhatIfResponse, 'status'>>,
  Partial<Omit<PolicySearch, 'status'>> { status?: string; summary?: string }
export type InterpretResult = { intent: { intent: string }; result: InterpretPayload | null; message?: string };
export interface FeedbackItem { preference_id: string; kind: string; employee_name?: string | null; scope: string; strength: string; text: string; active: boolean }

export const api = {
  // auth & profile
  login: (email: string, password: string) => post<{ user: User; token: string }>('/api/auth/login', { email, password }),
  register: (email: string, password: string, name: string, role: Role) =>
    post<{ user: User; token: string }>('/api/auth/register', { email, password, name, role }),
  demoLogin: (role: Role, domain?: DomainId | 'flagship', employee_id?: string, reset = false) =>
    post<{ user: User; token: string }>('/api/auth/demo', { role, domain, employee_id, reset }, SOLVE_TIMEOUT),
  demoAccounts: () => get<DemoAccount[]>('/api/auth/demo-accounts'),
  googleLogin: (id_token: string) => post<{ user: User; token: string }>('/api/auth/google', { id_token }),
  me: () => get<Me>('/api/auth/me'),
  logout: (everywhere = false) => post<{ revoked: number }>('/api/auth/logout', { everywhere }),
  changePassword: (current_password: string, new_password: string) => post<{ user: User }>('/api/auth/change-password', { current_password, new_password }),
  sessions: () => get<ProfileData['sessions']>('/api/auth/sessions'),
  profile: () => get<ProfileData>('/api/profile'),
  updateProfile: (b: { name?: string; phone?: string; avatar?: string; notification_preferences?: Record<string, boolean> }) =>
    patch<{ user: User }>('/api/profile', b),
  solver: () => get<SolverStatus>('/api/system/solver'),

  // domains & onboarding
  domains: () => get<DomainSummary[]>('/api/domains'),
  domain: (id: DomainId) => get<DomainConfig>(`/api/domains/${id}`),
  validate: (raw: unknown) => post<ValidationReport>('/api/datasets/validate', raw),
  validateCsv: (schedule: File, employees: File | null, organization: { name: string; domain: DomainId }) => {
    const f = new FormData();
    f.append('schedule_csv', schedule);
    if (employees) f.append('employees_csv', employees);
    f.append('organization', JSON.stringify(organization));
    return upload<{ report: ValidationReport; dataset: unknown }>('/api/datasets/validate-csv', f);
  },
  loadDataset: (raw: unknown) => post<{ report: ValidationReport; workspace: WorkspaceSummary | null }>('/api/datasets/load', raw, SOLVE_TIMEOUT),
  loadDemo: (domain: DomainId) => post<{ report: ValidationReport; workspace: WorkspaceSummary }>(`/api/datasets/demo/${domain}`),
  workspace: () => get<WorkspaceSummary>('/api/workspace'),
  scenarios: () => get<{ id: string; name: string; domain: DomainId }[]>('/api/scenarios'),
  loadScenario: (name: string) => post<{ report: ValidationReport; workspace: WorkspaceSummary }>(`/api/datasets/scenario/${encodeURIComponent(name)}`, {}, SOLVE_TIMEOUT),
  conflicts: () => get<ScheduleConflict[]>('/api/conflicts'),
  resolveConflicts: (conflict_ids?: string[]) => post<Proposal>('/api/conflicts/resolve', { conflict_ids }, SOLVE_TIMEOUT),
  conflictAssistant: () => get<ConflictAssistant>('/api/conflicts/assistant'),

  // operations
  dashboard: () => get<Dashboard>('/api/dashboard'),
  employees: () => get<Employee[]>('/api/employees'),
  schedule: () => get<ScheduleRow[]>('/api/schedule'),
  reportDisruption: (b: { text?: string; structured?: Record<string, unknown>; preset_id?: string }) =>
    post<DisruptionResponse>('/api/disruptions', b),
  disruptions: () => get<DisruptionRecord[]>('/api/disruptions'),
  dismissDisruption: (id: string) => post<DisruptionRecord>(`/api/disruptions/${encodeURIComponent(id)}/dismiss`),
  reschedule: (disruption_ids?: string[]) => post<Proposal>('/api/reschedule', { disruption_ids }, SOLVE_TIMEOUT),
  latestProposal: () => get<Proposal | null>('/api/reschedule/latest'),
  proposal: (id: string) => get<Proposal>(`/api/reschedule/${encodeURIComponent(id)}`),
  whatIf: (proposal_id: string, text: string) => post<WhatIfResponse>('/api/what-if', { proposal_id, text }, SOLVE_TIMEOUT),
  simulate: (proposal_id: string, action: SimulationAction) => post<Simulation>('/api/what-if/simulate', { proposal_id, action }, SOLVE_TIMEOUT),
  approve: (proposal_id: string, option_id?: string, notes = '', allow_partial = false) =>
    post<{ version: Version; notifications: Notification[]; recognition: RewardEligibility[] }>('/api/reschedule/approve', { proposal_id, option_id, notes, allow_partial }),
  reject: (proposal_id: string, reason = '') => post<Proposal>('/api/reschedule/reject', { proposal_id, reason }),
  interpret: (text: string) => post<InterpretResult>('/api/ai/interpret', { text }, SOLVE_TIMEOUT),
  feedback: (text: string) => post<{ status: string; summary?: string }>('/api/feedback', { text }),
  feedbackList: () => get<FeedbackItem[]>('/api/feedback'),
  repairCenter: (include_hidden = false) => get<RepairCenter>(`/api/repair-center?include_hidden=${include_hidden}`),
  hideRepair: (id: string) => post<{ id: string; hidden: boolean }>(`/api/repair-center/${encodeURIComponent(id)}/hide`),
  unhideRepair: (id: string) => post<{ id: string; hidden: boolean }>(`/api/repair-center/${encodeURIComponent(id)}/unhide`),
  completeRepair: (id: string) => post<{ proposal_id: string; completed: RewardEligibility[] }>(`/api/repair-center/${encodeURIComponent(id)}/complete`),

  // workforce
  staffingGaps: () => get<StaffingGap[]>('/api/staffing-gaps'),
  findEmployees: (b: WorkforceForm) => post<CandidateSearch>('/api/workforce/find', b),
  workforceRequests: () => get<WorkforceRequest[]>('/api/workforce-requests'),
  workforceRequest: (id: string) => get<WorkforceRequest>(`/api/workforce-requests/${encodeURIComponent(id)}`),
  createWorkforceRequest: (b: WorkforceForm) => post<WorkforceRequest>('/api/workforce-requests', b),
  requestVolunteers: (id: string, mode: 'volunteers' | 'broadcast' | 'escalate') =>
    post<{ request: WorkforceRequest; invited: string[] }>(`/api/workforce-requests/${encodeURIComponent(id)}/volunteers`, { mode }),
  assignWorkforce: (id: string, employee_id: string) => post<WorkforceRequest>(`/api/workforce-requests/${encodeURIComponent(id)}/assign`, { employee_id }),
  decideVolunteer: (id: string, employee_id: string, approve: boolean) =>
    post<WorkforceRequest>(`/api/workforce-requests/${encodeURIComponent(id)}/volunteers/${encodeURIComponent(employee_id)}/decision`, { approve }),
  completeAssignment: (id: string, employee_id: string) =>
    post<WorkforceRequest>(`/api/workforce-requests/${encodeURIComponent(id)}/assignments/${encodeURIComponent(employee_id)}/complete`),
  cancelWorkforce: (id: string) => post<WorkforceRequest>(`/api/workforce-requests/${encodeURIComponent(id)}/cancel`),
  respondOpportunity: (id: string, accept: boolean) => post<WorkforceRequest>(`/api/workforce-requests/${encodeURIComponent(id)}/respond`, { accept }),

  // admin requests
  adminRequests: () => get<AdminRequest[]>('/api/admin-requests'),
  createAdminRequest: (b: { type: AdminRequestType; title: string; message: string; target: { kind: string; value: unknown }; severity?: number }) =>
    post<AdminRequest>('/api/admin-requests', b),
  respondAdminRequest: (id: string, action: RequestAction, note = '') =>
    post<AdminRequest>(`/api/admin-requests/${encodeURIComponent(id)}/respond`, { action, note }),
  closeAdminRequest: (id: string) => post<AdminRequest>(`/api/admin-requests/${encodeURIComponent(id)}/close`),

  // employees, imports, templates
  directory: () => get<DirectoryEmployee[]>('/api/employees/directory'),
  fairness: (window?: number) => get<{ window_days: number; employees: FairnessProfile[] }>(`/api/fairness${window ? `?window=${window}` : ''}`),
  addEmployee: (b: Record<string, string>) => post<EmployeeImportResult>('/api/employees', b),
  updateEmployee: (id: string, b: Partial<Employee>) => patch<Employee>(`/api/employees/${encodeURIComponent(id)}`, b),
  setEmployeeStatus: (id: string, status: 'active' | 'inactive', reason = '') =>
    post<{ employee: Employee; disruptions: string[] }>(`/api/employees/${encodeURIComponent(id)}/status`, { status, reason }),
  createEmployeeLogins: () => post<{ created: number; credentials_token: string; expires_in_s: number }>('/api/employees/logins'),
  resetPassword: (id: string) => post<{ credentials_token: string; expires_in_s: number }>(`/api/employees/${encodeURIComponent(id)}/reset-password`),
  previewEmployeeImport: (file: File) => upload<ImportJob>('/api/employees/import/preview', fileForm(file)),
  confirmEmployeeImport: (jobId: string) => post<EmployeeImportResult>(`/api/employees/import/${encodeURIComponent(jobId)}/confirm`),
  downloadCredentials: (token: string) => download('POST', `/api/credentials/${encodeURIComponent(token)}`, 'resqwork-temporary-passwords.xlsx'),
  downloadTemplate: (name: 'employees.csv' | 'employees.xlsx' | 'schedule.csv' | 'schedule.xlsx' | 'constraints.csv' | 'constraints.json'
    | 'sample-schedule.csv' | 'sample-employees.csv') =>
    download('GET', `/api/templates/${name}`, `resqwork-${name}`),
  previewScheduleImport: (file: File) => upload<ImportJob>('/api/schedule/import/preview', fileForm(file)),
  confirmScheduleImport: (jobId: string, include_warnings: boolean) =>
    post<{ imported: number; version: string; skipped: number }>(`/api/schedule/import/${encodeURIComponent(jobId)}/confirm`, { include_warnings }),

  // constraint center
  constraints: () => get<ConstraintCatalog>('/api/constraints'),
  updateConstraint: (id: string, b: { value?: number; weight?: number; enabled?: boolean }) =>
    patch<ConstraintRow>(`/api/constraints/${encodeURIComponent(id)}`, b),
  removeConstraint: (id: string) => del<{ removed: string }>(`/api/constraints/${encodeURIComponent(id)}`),
  importConstraints: (file: File, apply: boolean) => upload<ConstraintImport>('/api/constraints/import', fileForm(file, { apply: String(apply) })),
  testConstraints: () => post<ConstraintTest>('/api/constraints/test'),

  // rewards & recognition
  rewards: () => get<RewardsOverview>('/api/rewards'),
  employeeRewards: (id: string) => get<EmployeeRewards>(`/api/employees/${encodeURIComponent(id)}/rewards`),
  saveRewardRules: (rules: RewardRule[]) => put<RewardConfig>('/api/rewards/config', { rules }),
  completeEligibility: (id: string) => post<RewardEligibility>(`/api/rewards/eligibility/${encodeURIComponent(id)}/complete`),
  approveReward: (id: string) => post<RewardEligibility>(`/api/rewards/eligibility/${encodeURIComponent(id)}/approve`),
  giveReward: (employee_id: string, trigger: 'team_contribution' | 'exceptional_performance', note: string) =>
    post<RewardEligibility>('/api/rewards/award', { employee_id, trigger, note }),

  // notifications
  notifications: () => get<Notification[]>('/api/notifications'),
  notificationAudit: () => get<NotificationAuditRow[]>('/api/notifications/audit'),
  notificationSummary: () => get<NotificationSummary>('/api/notifications/summary'),
  notificationSettings: () => get<NotificationSettings>('/api/notifications/settings'),
  saveNotificationSettings: (l2_escalation_minutes: number) => put<NotificationSettings>('/api/notifications/settings', { l2_escalation_minutes }),
  escalate: (force = false) => post<{ escalated: Notification[] }>('/api/notifications/escalate', { force }),

  // policies, versions, audit, analytics
  policies: () => get<PolicyOverview>('/api/policies'),
  policySearch: (q: string) => get<PolicySearch>(`/api/policies/search?q=${encodeURIComponent(q)}`),
  uploadPolicy: (file: File) => upload<{ policy_id: string; title: string; sections: number }>('/api/policies', fileForm(file)),
  versions: () => get<Version[]>('/api/versions'),
  audit: () => get<AuditEvent[]>('/api/audit'),
  analytics: () => get<Analytics>('/api/analytics'),
  availabilityRequests: () => get<EmployeeRequest[]>('/api/availability-requests'),
  decideRequest: (id: string, status: 'approved' | 'rejected' | 'needs_review', note = '') =>
    post<{ request: EmployeeRequest }>(`/api/availability-requests/${encodeURIComponent(id)}/decision`, { status, note }),
  recognition: () => get<{ config: RecognitionConfig; employees: RecognitionSummary[]; recent: Award[] }>('/api/recognition'),
  employeeRecognition: (id: string) => get<RecognitionSummary & { config: RecognitionConfig }>(`/api/employees/${encodeURIComponent(id)}/recognition`),
  recognize: (employee_id: string, category: string, note: string) => post<Award>('/api/recognition', { employee_id, category, note }),

  // employee self-service
  employeeView: (id: string) => get<EmployeeView>(`/api/employees/${encodeURIComponent(id)}/schedule`),
  employeeHome: (id: string) => get<EmployeeHome>(`/api/employees/${encodeURIComponent(id)}/home`),
  acknowledge: (id: string) => post<Notification>(`/api/notifications/${encodeURIComponent(id)}/acknowledge`),
  submitAvailability: (employeeId: string, b: { date: string; start?: string; end?: string; reason: string; kind?: string }) =>
    post<EmployeeRequest>(`/api/employees/${encodeURIComponent(employeeId)}/availability`, b),

  // voice (architecture kept; not part of the current product flow)
  voiceAlert: () => get<{ text: string; audio?: VoiceReply['audio'] }>('/api/voice/alert'),
  voice: (utterance: string, speak = false) => post<VoiceReply>('/api/voice', { utterance, speak }),
  voiceStatus: () => get<{ gemini: boolean; model?: string | null; server_tts: boolean }>('/api/voice/status'),
  voiceAudio: (blob: Blob) => {
    const f = new FormData();
    f.append('audio', blob, 'command.webm');
    return upload<VoiceReply>('/api/voice/audio', f);
  },
};
