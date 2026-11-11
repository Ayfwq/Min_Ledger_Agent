import axios, { AxiosError } from 'axios'

export const PASSWORD_KEY = 'ledger_app_password'

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

http.interceptors.request.use((config) => {
  const password = localStorage.getItem(PASSWORD_KEY)
  if (password) {
    config.headers.set('X-App-Password', password)
  }
  return config
})

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

http.interceptors.response.use(
  (resp) => resp,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      onUnauthorized?.()
    }
    return Promise.reject(error)
  },
)

export interface ApiErrorDetail {
  message?: string
  code?: string
  conflicts?: { field: string; existing: unknown; proposed: unknown; source: string }[]
}

export function apiError(error: unknown): { message: string; code?: string; conflicts?: ApiErrorDetail['conflicts'] } {
  const err = error as AxiosError<{ detail?: string | ApiErrorDetail }>
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return { message: detail }
  if (detail && typeof detail === 'object') {
    return { message: detail.message || '请求失败', code: detail.code, conflicts: detail.conflicts }
  }
  if (err.code === 'ECONNABORTED') return { message: '请求超时，请稍后重试' }
  return { message: err.message || '网络错误' }
}
