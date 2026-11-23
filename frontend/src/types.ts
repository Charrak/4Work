export type Role = "admin" | "mitarbeiter" | "benutzer";

export interface User {
  id: number; email: string; name: string; role: Role; is_active: boolean; is_locked: boolean;
  hourly_rate: number | null; vacation_days: number; weekly_hours: number | null; is_minor: boolean; is_minijob: boolean; minijob_limit: number | null; work_days: string; department_ids: number[]; version: number;
}
export interface Me extends User { permissions: string[] }
export interface Dept { id: number; name: string }
export interface Shift {
  id: number; department_id: number; user_id: number | null; user_name: string | null;
  start: string; end: string; note: string; published: boolean;
  claim_requires_approval: boolean; break_minutes: number; pending_claims: number; version: number;
}
export interface Claim { id: number; shift_id: number; user_id: number; user_name: string; status: string }
export interface Swap {
  id: number; shift_id: number; department_id: number; shift_start: string; shift_end: string;
  from_user_id: number; from_user_name: string; to_user_id: number | null; to_user_name: string | null; status: string;
}
export interface Leave {
  id: number; user_id: number; user_name: string; start_date: string; end_date: string;
  days: number; kind: string; note: string; status: string; decision_comment: string;
}
export interface LeaveBalance { user_id: number; year: number; entitlement: number; used: number; pending: number; remaining: number }
export interface TimeEntry {
  id: number; user_id: number; user_name: string; shift_id: number | null; clock_in: string;
  clock_out: string | null; minutes: number | null; approved: boolean; note: string;
}
export interface Message { id: number; user_id: number; user_name: string; text: string; created_at: string }
export interface ReportRow {
  user_id: number; name: string; email: string; planned_hours: number; worked_hours: number;
  approved_hours: number; overtime_hours: number; contract_hours: number;
  over_limit_days: number; over_limit_weeks: number; avg_weekly_hours_26w: number; avg_over_limit: boolean;
  night_hours: number; sunday_hours: number; holiday_hours: number; labor_cost: number; surcharge_cost: number; gross_cost: number;
  is_minijob: boolean; minijob_limit: number; minijob_months_over: number; is_minor: boolean;
}
export interface Report { rows: ReportRow[]; totals: Omit<ReportRow, "user_id" | "name" | "email"> }
export interface Wage { id: number; hourly_rate: number; valid_from: string }
export interface Absence { user_id: number; user_name: string; start_date: string; end_date: string; kind: string }
export interface ShiftTemplate { id: number; name: string; department_id: number | null; start_time: string; end_time: string; break_minutes: number; note: string }
export interface DocItem { id: number; user_id: number | null; user_name: string | null; category: string; title: string; filename: string; size: number; created_at: string }
export interface Company { company_name: string; privacy_contact: string }
export interface AuditEntry { id: number; user_id: number | null; action: string; detail: string; ip: string | null; created_at: string }
export interface BackupInfo { name: string; size_bytes: number; created_at: string }
export interface SystemInfo {
  version: string; environment: string; database: string; uptime_seconds: number; disk_free_gb: number; backups: number;
  stats: Record<string, number>;
}

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Administrator", mitarbeiter: "Mitarbeiter (Planer)", benutzer: "Benutzer (Schichtmitarbeiter)",
};
export const STATUS_LABEL: Record<string, string> = {
  pending: "Offen", approved: "Genehmigt", rejected: "Abgelehnt", cancelled: "Storniert",
  open: "Offen", accepted: "Angenommen, wartet auf Freigabe",
};

export const KIND_LABEL: Record<string, string> = {
  vacation: "Urlaub", sick: "Krankmeldung", special: "Sonderurlaub", wish: "Wunschfrei", absent: "abwesend",
};
export const DOC_CATEGORY: Record<string, string> = {
  vertrag: "Vertrag", attest: "Attest / Krankschreibung", schulung: "Schulung / Nachweis", allgemein: "Firmendokument", sonstiges: "Sonstiges",
};
export interface AvailabilityItem { weekday: number; start_time: string; end_time: string; note: string }
export const WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
