import { useEffect, useState, type FormEvent } from "react";
import { api, type Settings } from "../../api";

function listToText(values: string[]) {
  return values.join("\n");
}

function textToList(value: string) {
  return value
    .split(/\r?\n|,/)
    .map((v) => v.trim())
    .filter(Boolean);
}

export default function AdminFiltersPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [keywords, setKeywords] = useState("");
  const [allowlist, setAllowlist] = useState("");
  const [blocklist, setBlocklist] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const data = await api.getSettings();
        setSettings(data);
        setKeywords(listToText(data.staffing_keywords));
        setAllowlist(listToText(data.employment_allowlist));
        setBlocklist(listToText(data.employment_blocklist));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setError(null);
    setMessage(null);
    try {
      const updated = await api.updateSettings({
        staffing_keywords: textToList(keywords),
        employment_allowlist: textToList(allowlist),
        employment_blocklist: textToList(blocklist),
      });
      setSettings(updated);
      setMessage("Filter settings saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (!settings) {
    return (
      <section className="panel">
        {error ? <p className="error">{error}</p> : <p className="muted">Loading filters…</p>}
      </section>
    );
  }

  return (
    <section className="panel">
      <h2 style={{ marginTop: 0 }}>Staffing filters</h2>
      <p className="muted">
        Deterministic gate keywords and employment allow/block lists used before LLM classification.
      </p>
      {error && <p className="error">{error}</p>}
      {message && <p className="muted">{message}</p>}
      <form className="stack" onSubmit={onSubmit}>
        <label>
          Staffing keywords (one per line)
          <textarea value={keywords} onChange={(e) => setKeywords(e.target.value)} />
        </label>
        <label>
          Employment allowlist
          <textarea value={allowlist} onChange={(e) => setAllowlist(e.target.value)} />
        </label>
        <label>
          Employment blocklist
          <textarea value={blocklist} onChange={(e) => setBlocklist(e.target.value)} />
        </label>
        <button className="btn primary" type="submit">
          Save filters
        </button>
      </form>
    </section>
  );
}
