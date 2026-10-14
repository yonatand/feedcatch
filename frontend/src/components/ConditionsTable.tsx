import type { Condition } from '../api/types';

export function ConditionsTable({ conditions, compact }: { conditions: Condition[]; compact?: boolean }) {
  if (conditions.length === 0) {
    return <p className="muted small">No conditions recorded.</p>;
  }
  return (
    <div className="table-wrap">
      <table className={`table conditions${compact ? ' table-compact' : ''}`}>
        <thead>
          <tr>
            <th>Check</th>
            <th className="center">Passed</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {conditions.map((c, i) => (
            <tr key={`${c.check}-${i}`} className={c.passed ? '' : 'row-fail'}>
              <td className="nowrap mono cond-check">{c.check}</td>
              <td className="center cond-pass">
                {c.passed ? (
                  <span className="pass" aria-label="passed">
                    ✓
                  </span>
                ) : (
                  <span className="fail" aria-label="failed">
                    ✗
                  </span>
                )}
              </td>
              <td className="break cond-detail">{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
