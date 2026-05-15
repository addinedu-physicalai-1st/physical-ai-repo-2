export type Role = 'teacher' | 'parent'

export interface AuthUser {
  id: number
  email: string
  role: Role
  name: string
}

export interface Child {
  id: number
  name: string
  birth_date: string       // 'YYYY-MM-DD'
  class_name: string
  photo_url: string | null
  notes: string | null
  /** 보고서·호출용 이름. 비우면 서버에서 성 제거 추정 */
  given_name: string | null
}

export interface ParentInfo {
  id: number
  name: string
  email: string
  phone: string
  child_ids: number[]
}

export interface ChildDetail extends Child {
  parents: ParentInfo[]
  notes: string | null
}

export interface AttendanceRecord {
  child_id: number
  child_name: string
  check_in: string | null   // ISO datetime or null
  check_out: string | null
}

export interface MenuEntry {
  date: string              // 'YYYY-MM-DD'
  items: string[]
}

/** GET /api/reports·POST generate·PATCH 가 `attendance` 테이블을 붙여 줌 (교사·검증용). */
export interface ReportAttendanceDebug {
  has_check_in: boolean
  has_check_out: boolean
  check_in_kst: string | null
  check_out_kst: string | null
}

export interface Report {
  id: number
  child_id: number
  date: string
  content: string
  created_at: string
  updated_at: string | null
  attendance_debug?: ReportAttendanceDebug | null
}

export interface Photo {
  id: number
  child_id: number | null
  url: string               // /api/photos-static/... 등 (Vite proxy 경유)
  taken_at: string
  emotion: string | null
  emotion_score: number | null
  mode: string | null
}

export interface RegisterChildPayload {
  name: string
  birth_date: string
  class_name: string
  notes: string | null
  given_name?: string | null
}

export interface RegisterParentPayload {
  name: string
  email: string
  phone: string
  child_id: number
}

export interface RegisterParentResponse {
  parent: ParentInfo
  initial_password: string
}
