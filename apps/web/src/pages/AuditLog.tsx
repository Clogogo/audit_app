import { useEffect, useState } from 'react';
import { getAuditLog } from '../api/client';
import type { AuditLogEntry } from '../api/types';
import { Badge } from '../components/ui/badge';
import { formatDate } from '../lib/utils';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';

const actionColor: Record<string, string> = {
  create: 'bg-green-100 text-green-800',
  update: 'bg-blue-100 text-blue-800',
  delete: 'bg-red-100 text-red-800',
  match: 'bg-purple-100 text-purple-800',
  unmatch: 'bg-orange-100 text-orange-800',
};

export function AuditLog() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterEntity, setFilterEntity] = useState('all');

  useEffect(() => {
    getAuditLog({ entity_type: filterEntity !== 'all' ? filterEntity : undefined, limit: 100 })
      .then(setEntries)
      .finally(() => setLoading(false));
  }, [filterEntity]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Audit Log</h1>
        <Select value={filterEntity} onValueChange={setFilterEntity}>
          <SelectTrigger className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Entities</SelectItem>
            <SelectItem value="transaction">Transactions</SelectItem>
            <SelectItem value="bank_transaction">Bank Transactions</SelectItem>
            <SelectItem value="reconciliation">Reconciliation</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="text-center py-16 text-muted-foreground">Loading...</div>
      ) : entries.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">No audit entries yet</div>
      ) : (
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-4 py-3 font-medium">Timestamp</th>
                <th className="text-left px-4 py-3 font-medium">Entity</th>
                <th className="text-left px-4 py-3 font-medium">ID</th>
                <th className="text-left px-4 py-3 font-medium">Action</th>
                <th className="text-left px-4 py-3 font-medium">Changes</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {entries.map((e) => (
                <tr key={e.id} className="hover:bg-muted/30">
                  <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                    {new Date(e.timestamp).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 capitalize">{e.entity_type.replace('_', ' ')}</td>
                  <td className="px-4 py-3 text-muted-foreground">#{e.entity_id}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${actionColor[e.action] ?? 'bg-gray-100 text-gray-800'}`}>
                      {e.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground max-w-xs">
                    {e.old_values || e.new_values ? (
                      <details>
                        <summary className="cursor-pointer text-primary hover:underline">View changes</summary>
                        <div className="mt-2 space-y-1">
                          {e.old_values && (
                            <div>
                              <span className="font-medium">Before: </span>
                              <code className="bg-muted rounded px-1">{JSON.stringify(e.old_values)}</code>
                            </div>
                          )}
                          {e.new_values && (
                            <div>
                              <span className="font-medium">After: </span>
                              <code className="bg-muted rounded px-1">{JSON.stringify(e.new_values)}</code>
                            </div>
                          )}
                        </div>
                      </details>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
