// Types miroirs du contrat d'API ACC (Doc 08).
export type MissionStatus =
  | "CREATED" | "PLANNING" | "EXECUTING" | "AT_RISK" | "RECOVERING"
  | "WAITING_APPROVAL" | "COMPLETED" | "FAILED" | "ABORTED";

export type MissionHealth =
  | "HEALTHY" | "DEGRADED" | "AT_RISK" | "RECOVERING" | "FAILED" | "COMPLETED";

export interface MissionContext {
  deadline_hours: number;
  required_units: number;
  primary_supplier: string;
  fallback_suppliers: string[];
  selected_supplier: string | null;
  unit_price: number | null;
  purchase_amount: number | null;
  purchase_id: string | null;
  constraints: string[];
}

export interface MissionSummary {
  mission_id: string;
  objective: string;
  status: MissionStatus;
  health: MissionHealth;
  progress: number;
  priority: string;
  risk_level: string;
  current_stage: string;
  active_task_id: string | null;
  active_agent_id: string | null;
  checkpoint_id: string | null;
  approval_status: string | null;
  pending_approval_id: string | null;
  version: number;
  trace_id: string | null;
  required_units: number;
  deadline_hours: number;
  selected_supplier: string | null;
  purchase_amount: number | null;
  created_at: string;
  updated_at: string;
}

export interface MissionMetrics {
  mission_id: string;
  status: string;
  progress: number;
  disrupted: boolean;
  recovery_attempts: number;
  recovery_success: number;
  recovery_duration_s: number | null;
  approvals_requested: number;
  approvals_granted: number;
  approval_latency_s: number | null;
  policy_denials: number;
  blocked_actions: number;
  policy_violations: number;
  agents_involved: number;
  duplicate_executions: number;
  evidence: { checkpoints: number; events: number; audit_records: number };
}

export interface Task {
  task_id: string;
  type: string;
  title: string;
  status: string;
  assigned_agent: string | null;
  attempt: number;
  order: number;
}

export interface MissionDetail extends MissionSummary {
  context: MissionContext;
  tasks: Task[];
  latest_checkpoint: Checkpoint | null;
  metrics: MissionMetrics;
}

export interface Checkpoint {
  checkpoint_id: string;
  label: string;
  current_stage: string;
  mission_status: string;
  completed_tasks: string[];
  created_at: string;
}

export interface TimelineEvent {
  event_id: string;
  type: string;
  timestamp: string;
  message: string;
  source: string;
  actor: string | null;
  kind: string;
  payload: Record<string, unknown>;
  trace_id: string | null;
}

export interface Agent {
  agent_id: string;
  name: string;
  version: string;
  status: string;
  risk_level: string;
  capabilities: string[];
  denied_capabilities: string[];
  authority_level: string;
  runtime: string;
  description: string;
}

export interface RecoveryOption {
  strategy: string;
  label: string;
  rationale: string;
  estimated_risk: string;
  estimated_delay_hours: number;
  permitted: boolean;
  denial_reason: string | null;
  parameters: Record<string, unknown>;
}

export interface RecoveryAttempt {
  recovery_id: string;
  failed_component: string;
  failure_class: string;
  diagnosis: string;
  impact: string;
  options: RecoveryOption[];
  selected_option: string | null;
  reason: string;
  status: string;
  approval_id: string | null;
  policy_decision_id: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface Approval {
  approval_id: string;
  mission_id: string;
  agent_id: string;
  action: string;
  resource: string | null;
  amount: number | null;
  risk_level: string;
  reason: string;
  evidence: string[];
  status: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED";
  decided_by: string | null;
  requested_at: string;
  decided_at: string | null;
}

export interface TraceNode {
  type: "agent" | "recovery" | "policy" | "approval" | "security";
  name: string;
  status?: string;
  decision?: string;
  timestamp: string;
  finding?: string | null;
  confidence?: number | null;
  evidence?: string[];
  duration_ms?: number | null;
  diagnosis?: string;
  options?: RecoveryOption[];
  selected?: string | null;
  reason?: string;
  rule_id?: string;
  amount?: number | null;
  detail?: string;
  decided_by?: string | null;
  latency_s?: number | null;
}

export interface FleetMetrics {
  // null quand aucune mission n'a ete perturbee : une absence de donnees
  // n'est pas un score parfait.
  mission_continuity_rate: number | null;
  mission_success_rate: number | null;
  mission_failure_rate: number | null;
  recovery_success_rate: number | null;
  autonomous_recovery_rate: number | null;
  mean_time_to_recovery_s?: number | null;
  missions_total: number;
  missions_active: number;
  missions_at_risk: number;
  missions_disrupted: number;
  missions_recovered: number;
  fleet_health: Record<string, number>;
}

export interface PolicyBoundary {
  autonomous: string[];
  approval_required: string[];
  blocked: string[];
  /** The mode the fleet is ACTUALLY running — never a literal in the UI. */
  agent_mode?: string;
  thresholds: {
    purchase_autonomous_max: number;
    purchase_approval_max: number;
  };
  default: string;
}
