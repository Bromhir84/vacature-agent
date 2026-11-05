import { useEffect, useState, type FormEvent } from "react";
import {
  api,
  formatApiError,
  type CrawlRunResult,
  type ScanRun,
  type SourceDuplicate,
  type SourceProposal,
} from "../../api";

function reasonsText(reasons: SourceProposal["reasons"]): string {
  if (!reasons) return "—";
  if (Array.isArray(reasons)) return reasons.join("; ") || "—";
  return JSON.stringify(reasons);
}

function riskLabel(risk: number): string {
  return `${Math.round(risk * 100)}%`;
}

export default function AdminDiscoverPage() {
  const [queries, setQueries] = useState("");
  const [crawlQueries, setCrawlQueries] = useState("");
  const [proposals, setProposals] = useState<SourceProposal[]>([]);
  const [duplicates, setDuplicates] = useState<SourceDuplicate[]>([]);
  const [crawlRuns, setCrawlRuns] = useState<ScanRun[]>([]);
  const [lastCrawl, setLastCrawl] = useState<CrawlRunResult | null>(null);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load(status = statusFilter) {
    setError(null);
    try {
      const [rows, dups, runs] = await Promise.all([
        api.listProposals(status),
        api.listSourceDuplicates(),
        api.listCrawlRuns(),
      ]);
      setProposals(rows);
      setDuplicates(dups);
      setCrawlRuns(runs);
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  async function onPropose(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const list = queries
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (!list.length) {
      setError("Paste at least one company name, domain, or URL");
      return;
    }
    setBusy(true);
    try {
      const result = await api.proposeSources(list);
      const parts = [
        `${result.created.length} created`,
        `${result.updated.length} updated`,
        `${result.skipped.length} skipped`,
      ];
      setMessage(`Propose finished: ${parts.join(", ")}`);
      if (result.skipped.length) {
        setMessage(
          (prev) =>
            `${prev}. Skipped: ${result.skipped.map((s) => `${s.query} (${s.reason})`).join("; ")}`,
        );
      }
      setStatusFilter("pending");
      await load("pending");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onHarvest() {
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const result = await api.harvestPortals();
      setMessage(
        `Harvest finished: ${result.created.length} created, ${result.updated.length} updated, ${result.blocked} blocked`,
      );
      setStatusFilter("pending");
      await load("pending");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onWebCrawl() {
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const list = crawlQueries
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      const result = await api.runWebCrawl(list.length ? { queries: list } : {});
      setLastCrawl(result);
      setMessage(
        `Web crawl finished: ${result.upserted} URLs upserted, ${result.proposals_created} proposals, ` +
          `${result.skipped_broker} broker skips, ${result.skipped_low_score} low-score skips, ` +
          `${result.skipped_domain} same-domain skips, ${result.skipped_unusable} unusable skips, ` +
          `${result.skipped_recent} recently crawled skips` +
          (result.rejudged_discarded
            ? `, rejudged discarded ${result.rejudged_discarded}`
            : "") +
          (result.avg_relevance
            ? `, avg relevance ${Math.round(result.avg_relevance * 100)}%`
            : ""),
      );
      setStatusFilter("pending");
      await load("pending");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onRejudgeCrawl() {
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const result = await api.rejudgeCrawl();
      setMessage(
        `Rejudge finished: reviewed ${result.reviewed}, kept ${result.kept}, discarded ${result.discarded}`,
      );
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onClearCrawl() {
    if (
      !confirm(
        "Wipe all Open Web Crawl listings, crawl runs, and crawl proposals? This cannot be undone.",
      )
    ) {
      return;
    }
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const result = await api.clearCrawl();
      setLastCrawl(null);
      setMessage(
        `Crawl results cleared: ${result.listings} listings, ${result.runs} runs, ${result.proposals} proposals, ${result.visits} visits`,
      );
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onApprove(proposal: SourceProposal) {
    setError(null);
    setMessage(null);
    const highRisk = proposal.kind === "broker" || proposal.broker_risk >= 0.7;
    let force = false;
    if (highRisk) {
      force = confirm(
        `“${proposal.name}” looks high broker risk (${riskLabel(proposal.broker_risk)}). Approve anyway?`,
      );
      if (!force) return;
    }
    try {
      const source = await api.approveProposal(proposal.id, force);
      setMessage(`Approved → source “${source.name}” (disabled until you enable it)`);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function onReject(proposal: SourceProposal) {
    setError(null);
    setMessage(null);
    try {
      await api.rejectProposal(proposal.id);
      setMessage(`Rejected “${proposal.name}”`);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <section className="panel">
        <h1 style={{ margin: 0 }}>Discover career pages</h1>
        <p className="muted" style={{ margin: "0.25rem 0 0" }}>
          Paste companies or run a portal harvest. Proposals are scored for broker risk; approve
          creates a disabled agent source.
        </p>
        {error && <p className="error">{error}</p>}
        {message && <p className="muted">{message}</p>}
      </section>

      {duplicates.length > 0 && (
        <section className="panel">
          <h2 style={{ marginTop: 0 }}>Overlapping sources</h2>
          <p className="muted">
            These existing sources look like doubles (same career site or covered URL). Remove one
            under Sources if they are redundant.
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Source A</th>
                <th>Source B</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {duplicates.map((dup) => (
                <tr key={`${dup.left_id}-${dup.right_id}`}>
                  <td>
                    <strong>{dup.left_name}</strong>
                    <div className="muted">{dup.left_url}</div>
                  </td>
                  <td>
                    <strong>{dup.right_name}</strong>
                    <div className="muted">{dup.right_url}</div>
                  </td>
                  <td className="muted">{dup.reasons.join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>Propose from names / domains / URLs</h2>
        <form className="stack" onSubmit={onPropose}>
          <label>
            One per line
            <textarea
              value={queries}
              onChange={(e) => setQueries(e.target.value)}
              rows={6}
              placeholder={"anwb.nl\nPort of Rotterdam\nhttps://werkenbij.example.nl/vacatures"}
            />
          </label>
          <div className="row">
            <button className="btn primary" type="submit" disabled={busy}>
              Propose
            </button>
            <button className="btn" type="button" disabled={busy} onClick={() => void onHarvest()}>
              Run portal harvest
            </button>
          </div>
        </form>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>Web crawl</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Open-web BFS from portals + DuckDuckGo queries. Detail URLs land under Listings → New
          (source “Open Web Crawl”) with a heuristic relevance score. Full verification comes later.
        </p>
        <div className="stack">
          <label>
            Optional search queries (one per line; empty = defaults)
            <textarea
              value={crawlQueries}
              onChange={(e) => setCrawlQueries(e.target.value)}
              rows={4}
              placeholder={"vacature ICT inhuur\nwerken bij vacatures ICT"}
            />
          </label>
          <div className="row">
            <button className="btn primary" type="button" disabled={busy} onClick={() => void onWebCrawl()}>
              Run web crawl
            </button>
            <button className="btn" type="button" disabled={busy} onClick={() => void onRejudgeCrawl()}>
              Rejudge survivors
            </button>
            <button className="btn danger" type="button" disabled={busy} onClick={() => void onClearCrawl()}>
              Clear crawl results
            </button>
          </div>
          {lastCrawl && (
            <p className="muted" style={{ margin: 0 }}>
              Last run: fetched {lastCrawl.pages_fetched} pages · upserted {lastCrawl.upserted} ·
              dups {lastCrawl.skipped_dup} · domains {lastCrawl.skipped_domain} · unusable{" "}
              {lastCrawl.skipped_unusable} · brokers {lastCrawl.skipped_broker} · low score{" "}
              {lastCrawl.skipped_low_score} · proposals {lastCrawl.proposals_created}
              {lastCrawl.avg_relevance > 0
                ? ` · avg relevance ${Math.round(lastCrawl.avg_relevance * 100)}%`
                : ""}
            </p>
          )}
          {crawlRuns.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Status</th>
                  <th>Discovered</th>
                  <th>Upserted</th>
                  <th>Summary</th>
                </tr>
              </thead>
              <tbody>
                {crawlRuns.slice(0, 5).map((run) => (
                  <tr key={run.id}>
                    <td>{new Date(run.started_at).toLocaleString()}</td>
                    <td>
                      <span className="badge">{run.status}</span>
                    </td>
                    <td>{run.discovered}</td>
                    <td>{run.upserted}</td>
                    <td className="muted" style={{ maxWidth: "28rem" }}>
                      {(run.errors || "").slice(0, 160)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Proposals</h2>
          <div className="tabs">
            {["pending", "blocked", "approved", "rejected"].map((status) => (
              <button
                key={status}
                type="button"
                className={statusFilter === status ? "active" : ""}
                onClick={() => setStatusFilter(status)}
              >
                {status}
              </button>
            ))}
          </div>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Kind</th>
              <th>Risk</th>
              <th>Origin</th>
              <th>Reasons</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {proposals.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No {statusFilter} proposals
                </td>
              </tr>
            )}
            {proposals.map((proposal) => (
              <tr key={proposal.id}>
                <td>
                  <strong>{proposal.name}</strong>
                  <div className="muted">
                    <a href={proposal.career_url} target="_blank" rel="noreferrer">
                      {proposal.career_url}
                    </a>
                  </div>
                  {proposal.query && <div className="muted">query: {proposal.query}</div>}
                </td>
                <td>
                  <span className="badge">{proposal.kind}</span>
                </td>
                <td>{riskLabel(proposal.broker_risk)}</td>
                <td>{proposal.origin}</td>
                <td className="muted">{reasonsText(proposal.reasons)}</td>
                <td>
                  {statusFilter === "pending" && (
                    <div className="actions">
                      <button className="btn primary" onClick={() => void onApprove(proposal)}>
                        Approve
                      </button>
                      <button className="btn danger" onClick={() => void onReject(proposal)}>
                        Reject
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
