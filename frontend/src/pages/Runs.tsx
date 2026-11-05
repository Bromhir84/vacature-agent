import { useEffect, useState } from "react";
import { api, type ScanRun } from "../api";

export default function RunsPage() {
  const [runs, setRuns] = useState<ScanRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      setRuns(await api.listScans());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className="panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h1 style={{ margin: 0 }}>Runs</h1>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            Recent scan status per source.
          </p>
        </div>
        <button className="btn" onClick={() => void load()}>
          Refresh
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <table className="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Source</th>
            <th>Status</th>
            <th>Discovered</th>
            <th>Upserted</th>
            <th>Classified</th>
            <th>Candidates</th>
            <th>Started</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>{run.id}</td>
              <td>{run.source_name || run.source_id || "—"}</td>
              <td>
                <span className="badge">{run.status}</span>
              </td>
              <td>{run.discovered}</td>
              <td>{run.upserted}</td>
              <td>{run.classified}</td>
              <td>{run.candidates}</td>
              <td>{new Date(run.started_at).toLocaleString()}</td>
              <td className={run.errors ? "error" : undefined}>
                {run.errors ? "Error" : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
