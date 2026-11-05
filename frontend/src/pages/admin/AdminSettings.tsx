import { useEffect, useState, type FormEvent } from "react";
import { api, type Settings } from "../../api";

export default function AdminSettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    setError(null);
    try {
      const data = await api.getSettings();
      setSettings(data);
      setApiKeyInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const body: Partial<Settings> & { llm_api_key?: string; clear_llm_api_key?: boolean } = {
        llm_base_url: settings.llm_base_url,
        llm_model: settings.llm_model,
        scan_interval_hours: settings.scan_interval_hours,
        confidence_candidate: settings.confidence_candidate,
        confidence_review: settings.confidence_review,
        agent_max_listings: settings.agent_max_listings,
        agent_max_pages: settings.agent_max_pages,
      };
      if (apiKeyInput.trim()) {
        body.llm_api_key = apiKeyInput.trim();
      }
      const updated = await api.updateSettings(body);
      setSettings(updated);
      setApiKeyInput("");
      setMessage("Admin settings saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function clearApiKey() {
    if (!confirm("Clear the stored LLM API key?")) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateSettings({ clear_llm_api_key: true });
      setSettings(updated);
      setApiKeyInput("");
      setMessage("LLM API key cleared (env fallback still applies if set)");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (!settings) {
    return (
      <section className="panel">
        {error ? <p className="error">{error}</p> : <p className="muted">Loading admin settings…</p>}
      </section>
    );
  }

  return (
    <section className="panel">
      <h2 style={{ marginTop: 0 }}>LLM & scanner</h2>
      <p className="muted">
        STACKIT OpenAI-compatible endpoint. Key source: <strong>{settings.llm_source}</strong>
        {settings.llm_api_key_set ? ` (${settings.llm_api_key_masked})` : " — not configured"}.
      </p>
      {error && <p className="error">{error}</p>}
      {message && <p className="muted">{message}</p>}

      <form className="stack" onSubmit={onSubmit}>
        <fieldset className="fieldset">
          <legend>STACKIT / LLM</legend>
          <label>
            LLM base URL
            <input
              value={settings.llm_base_url}
              onChange={(e) => setSettings({ ...settings, llm_base_url: e.target.value })}
              placeholder="https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1"
              required
            />
          </label>
          <label>
            LLM model
            <input
              value={settings.llm_model}
              onChange={(e) => setSettings({ ...settings, llm_model: e.target.value })}
              placeholder="Qwen/Qwen3.8-27B"
              required
            />
          </label>
          <label>
            LLM API key
            <input
              type="password"
              autoComplete="off"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder={
                settings.llm_api_key_set
                  ? `Stored: ${settings.llm_api_key_masked} — enter a new key to replace`
                  : "Paste STACKIT auth token"
              }
            />
          </label>
          <div className="row">
            <button className="btn danger" type="button" onClick={() => void clearApiKey()} disabled={saving}>
              Clear stored key
            </button>
          </div>
        </fieldset>

        <fieldset className="fieldset">
          <legend>Scanner</legend>
          <label>
            Scan interval (hours)
            <input
              type="number"
              step="0.25"
              min="0.25"
              value={settings.scan_interval_hours}
              onChange={(e) =>
                setSettings({ ...settings, scan_interval_hours: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Candidate confidence threshold
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={settings.confidence_candidate}
              onChange={(e) =>
                setSettings({ ...settings, confidence_candidate: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Needs-review confidence threshold
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={settings.confidence_review}
              onChange={(e) =>
                setSettings({ ...settings, confidence_review: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Agent max listings
            <input
              type="number"
              min="1"
              value={settings.agent_max_listings}
              onChange={(e) =>
                setSettings({ ...settings, agent_max_listings: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Agent max pages
            <input
              type="number"
              min="1"
              value={settings.agent_max_pages}
              onChange={(e) =>
                setSettings({ ...settings, agent_max_pages: Number(e.target.value) })
              }
            />
          </label>
        </fieldset>

        <button className="btn primary" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save admin settings"}
        </button>
      </form>
    </section>
  );
}
