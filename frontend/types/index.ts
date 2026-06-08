export interface PriceUpdate {
  ticker: string
  price: number
  previous_price: number
  daily_open: number
  daily_change_pct: number
  direction: 'up' | 'down' | 'unchanged'
  timestamp: string
}

export interface Position {
  ticker: string
  quantity: number
  avg_cost: number
  current_price: number
  unrealized_pnl: number
  pnl_pct: number
}

export interface Portfolio {
  cash_balance: number
  total_value: number
  positions: Position[]
}

export interface WatchlistItem {
  ticker: string
  price: number | null
  daily_change_pct: number
  direction: string
}

export interface Trade {
  ticker: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  executed_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  trades?: Array<{ ticker: string; side: string; quantity: number }>
  watchlist_changes?: Array<{ ticker: string; action: string }>
  errors?: string[]
}

export interface Snapshot {
  total_value: number
  recorded_at: string
}
