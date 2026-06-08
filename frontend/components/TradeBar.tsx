'use client'
import { useState, useEffect } from 'react'

interface TradeBarProps {
  selectedTicker: string | null
  onTradeExecuted: () => void
}

export default function TradeBar({ selectedTicker, onTradeExecuted }: TradeBarProps) {
  const [ticker, setTicker] = useState('')
  const [quantity, setQuantity] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (selectedTicker) setTicker(selectedTicker)
  }, [selectedTicker])

  async function executeTrade(side: 'buy' | 'sell') {
    const qty = parseFloat(quantity)
    if (!ticker || isNaN(qty) || qty <= 0) {
      setError('Enter a valid ticker and quantity')
      return
    }
    setError('')
    setSuccess('')
    setLoading(true)
    try {
      const res = await fetch('/api/portfolio/trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker: ticker.toUpperCase(), side, quantity: qty }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || 'Trade failed')
      } else {
        setSuccess(`${side.toUpperCase()} ${qty} ${ticker.toUpperCase()} @ $${data.price?.toFixed(2)}`)
        setQuantity('')
        onTradeExecuted()
        setTimeout(() => setSuccess(''), 3000)
      }
    } catch {
      setError('Network error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-[#161b22] border-t border-[#30363d]">
      <input
        value={ticker}
        onChange={e => setTicker(e.target.value.toUpperCase())}
        placeholder="TICKER"
        maxLength={5}
        className="w-20 bg-[#21262d] border border-[#30363d] text-[#e6edf3] font-mono text-xs px-2 py-1.5 rounded focus:outline-none focus:border-[#209dd7] placeholder-[#484f58]"
      />
      <input
        value={quantity}
        onChange={e => setQuantity(e.target.value)}
        placeholder="QTY"
        type="number"
        min="0"
        step="0.01"
        className="w-20 bg-[#21262d] border border-[#30363d] text-[#e6edf3] font-mono text-xs px-2 py-1.5 rounded focus:outline-none focus:border-[#209dd7] placeholder-[#484f58]"
      />
      <button
        onClick={() => executeTrade('buy')}
        disabled={loading}
        className="bg-[#753991] text-white font-mono text-xs px-3 py-1.5 rounded hover:bg-[#8b4aa8] disabled:opacity-50 transition-colors"
      >BUY</button>
      <button
        onClick={() => executeTrade('sell')}
        disabled={loading}
        className="border border-[#753991] text-[#753991] font-mono text-xs px-3 py-1.5 rounded hover:bg-[#753991] hover:text-white disabled:opacity-50 transition-colors"
      >SELL</button>
      {error && <span className="text-[#f85149] font-mono text-xs">{error}</span>}
      {success && <span className="text-[#3fb950] font-mono text-xs">{success}</span>}
    </div>
  )
}
