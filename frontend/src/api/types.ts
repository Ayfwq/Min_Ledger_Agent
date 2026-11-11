export type InputKind = 'text' | 'image'
export type InputStatus =
  | 'pending'
  | 'processing'
  | 'needs_clarification'
  | 'ready_for_review'
  | 'confirmed'
  | 'rejected'
  | 'failed'
export type DraftStatus = 'drafting' | 'needs_clarification' | 'ready_for_review' | 'confirmed' | 'rejected'

export interface ImageInfo {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  width: number | null
  height: number | null
  url: string
}

export interface Warning {
  code: string
  field?: string
  severity: 'error' | 'warning' | 'info'
  message: string
}

export interface DuplicateCandidate {
  kind: 'bill' | 'draft'
  id: string
  amount: number
  txn_date: string
  merchant: string | null
  score: number
  reason: string
}

export interface MerchantSuggestion {
  matched: boolean
  merchant: { id: string; name: string; category: string; score: number; confidence: number } | null
  candidates: { id: string; name: string; category: string; score: number; confidence: number }[]
}

export interface Draft {
  id: string
  input_id: string
  seq: number
  status: DraftStatus
  amount: string | null
  currency: string
  txn_date: string | null
  merchant: string | null
  category: string | null
  note: string | null
  field_sources: Record<string, string>
  confidence: Record<string, number>
  warnings: Warning[]
  suggestions: {
    merchant?: MerchantSuggestion
    duplicate?: { count: number; checked_window_days?: number }
    datasource_errors?: Record<string, string>
  }
  duplicate_candidates: DuplicateCandidate[]
  conflict: Record<string, { existing: string; proposed: string }> | null
  bill_id: string | null
  input_kind?: InputKind | null
  input_text?: string | null
  created_at: string
  updated_at: string
}

export interface Clarification {
  id: string
  input_id: string
  draft_id: string | null
  field: string
  kind: 'missing' | 'conflict'
  status: 'open' | 'answered' | 'unknown' | 'cancelled' | 'resolved'
  blocking: boolean
  question: string
  reason: string | null
  options: Record<string, string> | null
  answer: Record<string, string> | null
  round: number
  created_at: string
  answered_at: string | null
}

export interface TraceEvent {
  id: number
  input_id: string
  draft_id: string | null
  step: string
  status: 'started' | 'ok' | 'failed' | 'retried'
  message: string | null
  payload: Record<string, unknown> | null
  duration_ms: number | null
  created_at: string
}

export interface DataSourceCall {
  id: string
  input_id: string
  draft_id: string | null
  source: 'duplicate_check' | 'merchant_catalog'
  status: 'ok' | 'failed' | 'skipped'
  request: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error: string | null
  latency_ms: number | null
  created_at: string
}

export interface InputItem {
  id: string
  kind: InputKind
  raw_text: string | null
  status: InputStatus
  failure_step: string | null
  failure_reason: string | null
  image: ImageInfo | null
  draft_count: number
  open_clarifications: number
  created_at: string
  updated_at: string
}

export interface InputDetail extends InputItem {
  drafts: Draft[]
  clarifications: Clarification[]
  trace_events: TraceEvent[]
  datasource_calls: DataSourceCall[]
}

export interface Bill {
  id: string
  draft_id: string
  input_id: string
  amount: string
  currency: string
  txn_date: string
  merchant: string | null
  category: string | null
  note: string | null
  created_at: string
}

export interface Stats {
  bills: number
  total_amount: number
  pending_review: number
  needs_clarification: number
  inputs: number
}

export const FIELD_LABELS: Record<string, string> = {
  amount: '金额',
  txn_date: '日期',
  merchant: '商户',
  category: '类别',
  note: '备注',
}
