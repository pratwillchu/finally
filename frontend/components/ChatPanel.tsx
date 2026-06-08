'use client'
import { useState, useRef, useEffect } from 'react'
import type { ChatMessage } from '@/types'

interface ChatPanelProps {
  onTradeExecuted: () => void
  onWatchlistChanged: () => void
}

export default function ChatPanel({ onTradeExecuted, onWatchlistChanged }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: "Hello! I'm FinAlly, your AI trading assistant. Ask me to analyze your portfolio, suggest trades, or manage your watchlist." }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function sendMessage() {
    const msg = input.trim()
    if (!msg || loading) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setLoading(true)
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      })
      const data = await res.json()
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: data.message,
        trades: data.trades,
        watchlist_changes: data.watchlist_changes,
        errors: data.errors,
      }
      setMessages(prev => [...prev, assistantMsg])
      if (data.trades?.length > 0) onTradeExecuted()
      if (data.watchlist_changes?.length > 0) onWatchlistChanged()
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-[#161b22] border-l border-[#30363d]">
      <div className="px-3 py-2 border-b border-[#30363d] flex items-center gap-2">
        <div className="w-2 h-2 rounded-full bg-[#753991]"></div>
        <span className="text-[#ecad0a] font-mono text-xs font-bold tracking-widest">FINALLY AI</span>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded px-3 py-2 text-xs font-mono ${
              msg.role === 'user'
                ? 'bg-[#753991] text-white ml-2'
                : 'bg-[#21262d] text-[#e6edf3] border border-[#30363d]'
            }`}>
              <p className="leading-relaxed">{msg.content}</p>
              {msg.trades && msg.trades.length > 0 && (
                <div className="mt-1.5 space-y-0.5">
                  {msg.trades.map((t, j) => (
                    <div key={j} className="text-[#3fb950] text-xs">
                      ✓ {t.side.toUpperCase()} {t.quantity} {t.ticker}
                    </div>
                  ))}
                </div>
              )}
              {msg.watchlist_changes && msg.watchlist_changes.length > 0 && (
                <div className="mt-1.5 space-y-0.5">
                  {msg.watchlist_changes.map((w, j) => (
                    <div key={j} className="text-[#209dd7] text-xs">
                      ✓ {w.action.toUpperCase()} {w.ticker} watchlist
                    </div>
                  ))}
                </div>
              )}
              {msg.errors && msg.errors.length > 0 && (
                <div className="mt-1.5">
                  {msg.errors.map((e, j) => (
                    <div key={j} className="text-[#f85149] text-xs">⚠ {e}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-[#21262d] border border-[#30363d] rounded px-3 py-2 text-[#8b949e] font-mono text-xs">
              <span className="animate-pulse">thinking...</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="p-2 border-t border-[#30363d]">
        <div className="flex gap-1">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
            placeholder="Ask FinAlly..."
            disabled={loading}
            className="flex-1 bg-[#21262d] border border-[#30363d] text-[#e6edf3] font-mono text-xs px-2 py-1.5 rounded focus:outline-none focus:border-[#753991] placeholder-[#484f58] disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="bg-[#753991] text-white font-mono text-xs px-3 py-1.5 rounded hover:bg-[#8b4aa8] disabled:opacity-50 transition-colors"
          >→</button>
        </div>
      </div>
    </div>
  )
}
