import { useState } from 'react'
import { AlertCircle, BarChart3, Info } from 'lucide-react'
import Header from './components/Header'
import Hero from './components/Hero'
import HowItWorks from './components/HowItWorks'
import InputPanel from './components/InputPanel'
import ResultCard from './components/ResultCard'
import EquityChart from './components/EquityChart'
import PnLChart from './components/PnLChart'
import Footer from './components/Footer'
import { MetricsSkeleton, ChartSkeleton } from './components/Skeleton'
import { runBacktest, errorMessage } from './api'

const scrollToSection = (id) => {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export default function App() {
  const [result, setResult] = useState(null)
  const [params, setParams] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [runId, setRunId] = useState(0)

  const handleRun = async (form) => {
    setLoading(true)
    setError(null)
    try {
      const data = await runBacktest(form)
      setResult(data)
      setParams(form)
      setRunId((n) => n + 1)
      if (window.innerWidth < 960) setTimeout(() => scrollToSection('results'), 50)
    } catch (err) {
      setError(errorMessage(err))
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const summary = params
    ? `${params.symbol} / ${params.strategy} / ${params.timeframe} / ${params.trade_option === 'Both' ? 'Buy and Sell' : `${params.trade_option} only`}`
    : ''

  return (
    <div className="app">
      <Header onNavigate={scrollToSection} />

      <main>
        <Hero onNavigate={scrollToSection} />
        <HowItWorks />

        <section className="section section--alt" id="backtest">
          <div className="container">
            <div className="section__head">
              <p className="eyebrow">Backtest Engine</p>
              <h2 className="section__title">Run Your Backtest</h2>
              <p className="section__lead">
                Configure a strategy, run it against historical data, and review every metric and
                chart in seconds.
              </p>
            </div>

            <div className="workspace">
              <InputPanel onRun={handleRun} loading={loading} />

              <div className="results" id="results">
                <div className="results__head">
                  <h3 className="panel__title">Results</h3>
                  {result && !loading && <span className="results__summary">{summary}</span>}
                </div>

                {loading && <MetricsSkeleton />}

                {!loading && error && (
                  <div className="alert alert--error" role="alert">
                    <AlertCircle size={18} />
                    <div>
                      <strong>Backtest failed</strong>
                      <p>{error}</p>
                    </div>
                  </div>
                )}

                {!loading && !error && !result && (
                  <div className="empty glass-card">
                    <BarChart3 size={40} strokeWidth={1.5} />
                    <p className="empty__title">No results yet</p>
                    <p className="empty__text">
                      Choose your settings and press Run Backtest to see how the strategy performed.
                    </p>
                  </div>
                )}

                {!loading && result && (
                  <>
                    {result.note && (
                      <div className="alert alert--info">
                        <Info size={16} />
                        <span>{result.note}</span>
                      </div>
                    )}
                    <ResultCard key={runId} result={result} params={params} />
                  </>
                )}
              </div>
            </div>

            {loading && (
              <div className="charts">
                <ChartSkeleton height={340} />
                <ChartSkeleton height={300} />
              </div>
            )}

            {!loading && result && (
              <div className="charts" key={runId}>
                <div className="fade-up">
                  <EquityChart
                    data={result.equity_curve}
                    startBalance={params.account_size}
                    subtitle={summary}
                  />
                </div>
                <div className="fade-up" style={{ animationDelay: '0.15s' }}>
                  <PnLChart data={result.daily_pnl} />
                </div>
              </div>
            )}
          </div>
        </section>
      </main>

      <Footer />
    </div>
  )
}
