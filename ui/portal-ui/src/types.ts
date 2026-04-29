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

export interface Report {
  id: number
  child_id: number
  date: string
  content: string
  created_at: string
  updated_at: string | null
}

export interface Photo {
  id: number
  child_id: number
  url: string               // /photos/... presigned path
  taken_at: string
  emotion: string | null
  mode: string | null
}

export interface RegisterChildPayload {
  name: string
  birth_date: string
  class_name: string
  notes: string | null
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
