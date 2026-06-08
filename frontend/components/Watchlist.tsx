'use client'
import { useState, useRef, useEffect } from 'react'
import type { WatchlistItem } from '@/types'
import type { PriceMap, PriceHistory } from '@/hooks/useMarketData'
import Sparkline from './Sparkline'

interface WatchlistProps {
  prices: PriceMap
  priceHistory: PriceHistory
  watchlist: WatchlistItem[]
  selectedTicker: string | null
  onSelectTicker: (t: string) => void
  onWatchlistChanged: () => void
}

export default function Watchlist({ prices, priceHistory, watchlist, selectedTicker, onSelectTicker, onWatchlistChanged }: WatchlistProps) {
  const [newTicker, setNewTicker] = useState('')
  const [error, setError] = useState('')
  const flashRef = useRef<Record<string, string>>({})
  const [flashMap, setFlashMap] = useState<Record<string, string>>({})

  useEffect(() => {
    const next: Record<string, string> = {}
    for (const [ticker, update] of Object.entries(prices)) {
      const prev = flashRef.current[ticker]
      if (prev !== undefined && prev !== String(update.price)) {
        next[ticker] = update.direction === 'up' ? 'price-flash-up' : 'price-flash-down'
      }
      flashRef.current[ticker] = String(update.price)
    }
    if (Object.keys(next).length > 0) {
      setFlashMap(prev => ({ ...prev, ...next }))
      const timers = Object.keys(next).map(t =>
        setTimeout(() => setFlashMap(prev => { const n = { ...prev }; delete n[t]; return n }), 650)
      )
      return () => timers.forEach(clearTimeout)
    }
  }, [prices])

  async function addTicker() {
    const t = newTicker.trim().toUpperCase()
    if (!t) return
    setError('')
    try {
      const res = await fetch('/api/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker: t }),
      })
      if (!res.ok) {
        const data = await res.json()
        setError(data.detail || 'Failed to add ticker')
        return
      }
      setNewTicker('')
      onWatchlistChanged()
    } catch {
      setError('Network error')
    }
  }

  async function removeTicker(ticker: string) {
    await fetch(`/api/watchlist/${ticker}`, { method: 'DELETE' })
    onWatchlistChanged()
  }

  return (
    <div className="flex flex-col h-full bg-[#161b22] border-r border-[#30363d]">
      <div className="px-3 py-2 border-b border-[#30363d]">
        <span className="text-[#ecad0a] font-mono text-xs font-bold tracking-widest">WATCHLIST</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {watchlist.map(item => {
          const live = prices[item.ticker]
          const price = live?.price ?? item.price
          const changePct = live?.daily_change_pct ?? item.daily_change_pct
          const isUp = changePct >= 0
          const history = priceHistory[item.ticker] ?? []
          const isSelected = selectedTicker === item.ticker

          return (
            <div
              key={item.ticker}
              onClick={() => onSelectTicker(item.ticker)}
              className={`group flex items-center px-3 py-2 cursor-pointer border-b border-[#21262d] hover:bg-[#21262d] transition-colors ${isSelected ? 'bg-[#21262d] border-l-2 border-l-[#ecad0a]' : ''} ${flashMap[item.ticker] ?? ''}`}
            >
              <div className="flex-1 min-w-0">
                <div className={`font-mono font-bold text-sm ${isSelected ? 'text-[#ecad0a]' : 'text-[#e6edf3]'}`}>{item.ticker}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="font-mono text-xs text-[#e6edf3]">
                    {price != null ? `$${price.toFixed(2)}` : '—'}
                  </span>
                  <span className={`font-mono text-xs ${isUp ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                    {isUp ? '+' : ''}{changePct.toFixed(2)}%
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Sparkline data={history.slice(-60)} width={56} height={20} />
                <button
                  onClick={e => { e.stopPropagation(); removeTicker(item.ticker) }}
                  className="opacity-0 group-hover:opacity-100 text-[#6e7681] hover:text-[#f85149] text-xs ml-1 transition-opacity"
                >×</button>
              </div>
            </div>
          )
        })}
      </div>
      <div className="p-2 border-t border-[#30363d]">
        <div className="flex gap-1">
          <input
            value={newTicker}
            onChange={e => setNewTicker(e.target.value.toUpperCase())}
            onKeyDown={e => e.key === 'Enter' && addTicker()}
            placeholder="ADD TICKER"
            maxLength={5}
            className="flex-1 bg-[#21262d] border border-[#30363d] text-[#e6edf3] font-mono text-xs px-2 py-1 rounded focus:outline-none focus:border-[#209dd7] placeholder-[#484f58]"
          />
          <button
            onClick={addTicker}
            className="bg-[#209dd7] text-white font-mono text-xs px-2 py-1 rounded hover:bg-[#1a8bc0] transition-colors"
          >+</button>
        </div>
        {error && <div className="text-[#f85149] text-xs mt-1 font-mono">{error}</div>}
      </div>
    </div>
  )
}
