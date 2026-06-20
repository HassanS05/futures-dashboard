import { PortfolioHero } from "@/components/dashboard/PortfolioHero";
import { AllocationChart } from "@/components/dashboard/AllocationChart";
import { Watchlist } from "@/components/dashboard/Watchlist";
import { MarketHeatmap } from "@/components/dashboard/MarketHeatmap";
import { PositionsTable } from "@/components/dashboard/PositionsTable";
import { AIInsights } from "@/components/dashboard/AIInsights";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Command Center</h1>
        <p className="text-sm text-muted">Your portfolio, markets & AI copilot — live.</p>
      </div>

      <PortfolioHero />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <AllocationChart />
        </div>
        <Watchlist />
      </div>

      <PositionsTable />

      <div className="grid gap-6 lg:grid-cols-2">
        <MarketHeatmap />
        <AIInsights />
      </div>
    </div>
  );
}
