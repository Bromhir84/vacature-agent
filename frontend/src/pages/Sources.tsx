import { useEffect, useState, type FormEvent } from "react";
import { api, formatApiError, type Source } from "../api";

const DEFAULT_FOCUS_KEYWORDS = [
  "inhuur",
  "detachering",
  "extern",
  "inlener",
  "interim",
  "zzp",
  "ICT",
];

const EMPTY_FORM = {
  name: "",
  base_url: "",
  adapter_key: "html",
  enabled: true,
  config: "{\n  \n}",
};

function agentConfigForUrl(url: string) {
  return {
    list_url: url,
    max_listings: 25,
    max_pages: 5,
    focus_keywords: DEFAULT_FOCUS_KEYWORDS,
  };
}

function originFromUrl(url: string) {
  try {
    return new URL(url).origin;
  } catch {
    return url;
  }
}

export default function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [quickName, setQuickName] = useState("");
  const [quickUrl, setQuickUrl] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      setSources(await api.listSources());
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function startEdit(source: Source) {
    setEditingId(source.id);
    setForm({
      name: source.name,
      base_url: source.base_url,
      adapter_key: source.adapter_key,
      enabled: source.enabled,
      config: JSON.stringify(source.config || {}, null, 2),
    });
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    let config: Record<string, unknown>;
    try {
      config = JSON.parse(form.config || "{}");
    } catch {
      setError("Config must be valid JSON");
      return;
    }
    const body = {
      name: form.name,
      base_url: form.base_url,
      adapter_key: form.adapter_key,
      enabled: form.enabled,
      config,
    };
    try {
      if (editingId) {
        await api.updateSource(editingId, body);
        setMessage("Source updated");
      } else {
        await api.createSource(body);
        setMessage("Source created");
      }
      setEditingId(null);
      setForm(EMPTY_FORM);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function onQuickAdd(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const url = quickUrl.trim();
    const name = quickName.trim();
    if (!name || !url) {
      setError("Name and career page URL are required");
      return;
    }
    try {
      // Validate URL early for clearer errors.
      new URL(url);
    } catch {
      setError("Career page URL must be a valid absolute URL");
      return;
    }
    try {
      await api.createSource({
        name,
        base_url: originFromUrl(url),
        adapter_key: "agent",
        enabled: true,
        config: agentConfigForUrl(url),
      });
      setMessage(`Agent source “${name}” created`);
      setQuickName("");
      setQuickUrl("");
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function toggleEnabled(source: Source) {
    await api.updateSource(source.id, { enabled: !source.enabled });
    await load();
  }

  async function remove(source: Source) {
    if (!confirm(`Delete source “${source.name}”?`)) return;
    await api.deleteSource(source.id);
    await load();
  }

  async function scan(source: Source) {
    setMessage(`Scan queued for ${source.name}`);
    await api.runSourceScan(source.id);
  }

  async function scanAll() {
    setMessage("Scan queued for all enabled sources");
    await api.runAllScans();
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1 style={{ margin: 0 }}>Sources</h1>
            <p className="muted" style={{ margin: "0.25rem 0 0" }}>
              Employer career sites via JSON, HTML, or agent adapters.
            </p>
          </div>
          <button className="btn primary" onClick={() => void scanAll()}>
            Scan all
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        {message && <p className="muted">{message}</p>}
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Adapter</th>
              <th>Enabled</th>
              <th>Last scan</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.id}>
                <td>
                  <strong>{source.name}</strong>
                  <div className="muted">{source.base_url}</div>
                </td>
                <td>
                  <span className="badge">{source.adapter_key}</span>
                </td>
                <td>{source.enabled ? "yes" : "no"}</td>
                <td>{source.last_scan_at ? new Date(source.last_scan_at).toLocaleString() : "—"}</td>
                <td>
                  <div className="actions">
                    <button className="btn" onClick={() => startEdit(source)}>
                      Edit
                    </button>
                    <button className="btn" onClick={() => void toggleEnabled(source)}>
                      {source.enabled ? "Disable" : "Enable"}
                    </button>
                    <button className="btn primary" onClick={() => void scan(source)}>
                      Scan
                    </button>
                    <button className="btn danger" onClick={() => void remove(source)}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>Quick add career URL</h2>
        <p className="muted">
          Paste any company career/overview URL; the agent discovers vacancy links (inhuur / ICT
          focus by default).
        </p>
        <form className="stack" onSubmit={onQuickAdd}>
          <label>
            Name
            <input
              value={quickName}
              onChange={(e) => setQuickName(e.target.value)}
              placeholder="e.g. Werken bij Example"
              required
            />
          </label>
          <label>
            Career page URL
            <input
              type="url"
              value={quickUrl}
              onChange={(e) => setQuickUrl(e.target.value)}
              placeholder="https://werkenbij.example.nl/vacatures"
              required
            />
          </label>
          <button className="btn primary" type="submit">
            Add agent source
          </button>
        </form>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0 }}>{editingId ? "Edit source" : "Add source (advanced)"}</h2>
        <form className="stack" onSubmit={onSubmit}>
          <label>
            Name
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </label>
          <label>
            Base URL
            <input
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              required
            />
          </label>
          <label>
            Adapter
            <select
              value={form.adapter_key}
              onChange={(e) => setForm({ ...form, adapter_key: e.target.value })}
            >
              <option value="json">json</option>
              <option value="html">html</option>
              <option value="agent">agent</option>
            </select>
          </label>
          <label>
            <span>
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              />{" "}
              Enabled
            </span>
          </label>
          <label>
            Config (JSON)
            <textarea
              value={form.config}
              onChange={(e) => setForm({ ...form, config: e.target.value })}
            />
          </label>
          <div className="row">
            <button className="btn primary" type="submit">
              {editingId ? "Save" : "Create"}
            </button>
            {editingId && (
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setEditingId(null);
                  setForm(EMPTY_FORM);
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      </section>
    </div>
  );
}
