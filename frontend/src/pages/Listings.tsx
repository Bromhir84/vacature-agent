import { useEffect, useState } from "react";
import { api, formatApiError, type Listing } from "../api";

const TABS = [
  { id: "new", label: "New" },
  { id: "open", label: "Open" },
  { id: "removed", label: "Removed" },
];

export default function ListingsPage() {
  const [status, setStatus] = useState("new");
  const [items, setItems] = useState<Listing[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load(nextStatus = status) {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.listListings(nextStatus));
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(status);
  }, [status]);

  async function openListing(item: Listing) {
    try {
      await api.markListingViewed(item.id);
    } catch (err) {
      setError(formatApiError(err));
      return;
    }
    window.open(item.url, "_blank", "noopener,noreferrer");
    await load();
  }

  return (
    <section className="panel">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.75rem" }}>
        <div>
          <h1 style={{ margin: 0 }}>Listings</h1>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            New vacancies, ones you’ve opened, and ones removed from the website.
          </p>
        </div>
        <button className="btn" onClick={() => void load()} disabled={loading}>
          Refresh
        </button>
      </div>

      <div className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={status === tab.id ? "active" : ""}
            onClick={() => setStatus(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Loading…</p>}
      {!loading && items.length === 0 && <p className="muted">No listings in this tab.</p>}

      <div>
        {items.map((item) => (
          <article key={item.id} className="listing">
            <h3>
              <button
                type="button"
                className="linkish"
                onClick={() => void openListing(item)}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  color: "inherit",
                  font: "inherit",
                  fontWeight: 700,
                  cursor: "pointer",
                  textAlign: "left",
                  textDecoration: "underline",
                }}
              >
                {item.title}
              </button>
            </h3>
            <div className="meta">
              <span className="badge">{item.source_name || `Source #${item.source_id}`}</span>
              {item.status === "removed" && (
                <span className="badge">Removed from website</span>
              )}
              {item.employment_type && <span>{item.employment_type}</span>}
              {item.location && <span>{item.location}</span>}
              {item.relevance_score != null && (
                <span>relevance {Math.round(item.relevance_score * 100)}%</span>
              )}
              {item.latest_confidence != null && (
                <span>confidence {item.latest_confidence.toFixed(2)}</span>
              )}
            </div>
            {(item.summary || item.description) && (
              <p className="muted" style={{ maxHeight: "4.5em", overflow: "hidden" }}>
                {item.summary ||
                  item.description!.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 280)}
              </p>
            )}
            <div className="actions">
              <button className="btn primary" onClick={() => void openListing(item)}>
                Open vacancy
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
