import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 60000,
})

export const getSymbols = () => api.get('/symbols').then((r) => r.data)
export const getStrategies = () => api.get('/strategies').then((r) => r.data)
export const runBacktest = (params) => api.post('/backtest', params).then((r) => r.data)

// Turn an axios error into a readable message
export function errorMessage(err) {
  if (err.response?.data?.detail) {
    const d = err.response.data.detail
    return typeof d === 'string' ? d : 'Invalid input. Please check your settings.'
  }
  if (err.code === 'ERR_NETWORK') {
    return 'Cannot reach the backtest server. Make sure the backend is running on http://localhost:8000.'
  }
  return err.message || 'Something went wrong. Please try again.'
}
