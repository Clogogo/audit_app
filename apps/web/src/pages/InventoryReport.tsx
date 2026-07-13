import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileBarChart, AlertCircle, AlertTriangle } from 'lucide-react';
import { getItemsReport } from '../api/client';
import type { ItemReport } from '../api/types';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

export function InventoryReport() {
  const [rows, setRows] = useState<ItemReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getItemsReport()
      .then(setRows)
      .catch(() => setError('Failed to load the report'))
      .finally(() => setLoading(false));
  }, []);

  const totals = rows.reduce(
    (acc, r) => ({
      purchasedQty: acc.purchasedQty + r.total_purchased_quantity,
      purchaseCost: acc.purchaseCost + r.total_purchase_cost,
      soldQty: acc.soldQty + r.total_sold_quantity,
      saleRevenue: acc.saleRevenue + r.total_sale_revenue,
      costedRevenue: acc.costedRevenue + r.costed_revenue,
      profit: acc.profit + r.total_profit,
    }),
    { purchasedQty: 0, purchaseCost: 0, soldQty: 0, saleRevenue: 0, costedRevenue: 0, profit: 0 }
  );
  // Blended margin across every item — total profit over costed revenue
  // (not total_sale_revenue, which also includes sales with no recorded
  // cost; total_profit never reflects those, so dividing by all revenue
  // would understate margin), and not an average of each row's own
  // margin % either, which would weight a low-volume item the same as a
  // high-volume one.
  const totalMarginPct = totals.costedRevenue > 0 ? (totals.profit / totals.costedRevenue) * 100 : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <FileBarChart className="h-6 w-6 text-primary" />
          Inventory Report
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          What was bought and what was sold, per item — click an item to see its full stock movement history
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : error ? null : rows.length === 0 ? (
        <Card>
          <CardContent className="pt-5">
            <p className="text-sm text-muted-foreground py-4 text-center">
              No items in the catalog yet. <Link to="/inventory/items" className="underline">Add an item first.</Link>
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Purchases &amp; Sales by Item</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[900px]">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="text-left py-2 pr-3 font-medium">Item</th>
                    <th className="text-left py-2 pr-3 font-medium">Category</th>
                    <th className="text-right py-2 pr-3 font-medium">On Hand</th>
                    <th className="text-right py-2 pr-3 font-medium">Purchased (qty)</th>
                    <th className="text-right py-2 pr-3 font-medium">Purchase Cost</th>
                    <th className="text-right py-2 pr-3 font-medium">Sold (qty)</th>
                    <th className="text-right py-2 pr-3 font-medium">Sale Revenue</th>
                    <th className="text-right py-2 pr-3 font-medium">Profit / Loss</th>
                    <th className="text-right py-2 pr-3 font-medium">Margin</th>
                    <th className="py-2"><span className="sr-only">Ledger</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rows.map((r) => (
                    <tr key={r.item_id} className="hover:bg-muted/30 transition-colors">
                      <td className="py-3 pr-3 font-medium">
                        {r.item_name}
                        {r.sales_missing_cost_count > 0 && (
                          <AlertTriangle
                            className="inline-block h-3.5 w-3.5 text-destructive ml-1.5 align-text-top"
                            aria-label={`${r.sales_missing_cost_count} sale(s) excluded from profit — no cost was recorded`}
                          />
                        )}
                      </td>
                      <td className="py-3 pr-3 text-muted-foreground">{r.category}</td>
                      <td className="py-3 pr-3 text-right">{r.quantity_on_hand}</td>
                      <td className="py-3 pr-3 text-right text-muted-foreground">{r.total_purchased_quantity}</td>
                      <td className="py-3 pr-3 text-right text-muted-foreground">{formatCurrency(r.total_purchase_cost)}</td>
                      <td className="py-3 pr-3 text-right text-muted-foreground">{r.total_sold_quantity}</td>
                      <td className="py-3 pr-3 text-right text-income">{formatCurrency(r.total_sale_revenue)}</td>
                      <td className={`py-3 pr-3 text-right font-medium ${r.total_profit < 0 ? 'text-destructive' : ''}`}>
                        {formatCurrency(r.total_profit)}
                      </td>
                      <td className="py-3 pr-3 text-right text-muted-foreground">{r.profit_margin_pct.toFixed(1)}%</td>
                      <td className="py-3 text-right">
                        <Link
                          to={`/inventory/movements?item=${r.item_id}`}
                          className="text-xs text-primary underline hover:no-underline whitespace-nowrap"
                        >
                          View Ledger
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t font-semibold">
                    <td colSpan={3} className="py-2 text-xs text-muted-foreground">Total</td>
                    <td className="py-2 text-right">{totals.purchasedQty}</td>
                    <td className="py-2 text-right">{formatCurrency(totals.purchaseCost)}</td>
                    <td className="py-2 text-right">{totals.soldQty}</td>
                    <td className="py-2 text-right text-income">{formatCurrency(totals.saleRevenue)}</td>
                    <td className={`py-2 text-right ${totals.profit < 0 ? 'text-destructive' : ''}`}>
                      {formatCurrency(totals.profit)}
                    </td>
                    <td className="py-2 text-right text-muted-foreground">{totalMarginPct.toFixed(1)}%</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
