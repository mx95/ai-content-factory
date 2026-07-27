import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Clapperboard, Loader2, Play, RefreshCw } from "lucide-react";
import "./styles.css";

const API_BASE = "/api";

function App() {
  const [topic, setTopic] = useState("Why do octopuses have three hearts?");
  const [language, setLanguage] = useState("English");
  const [duration, setDuration] = useState(45);
  const [scripts, setScripts] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadScripts() {
    const response = await fetch(`${API_BASE}/scripts`);
    if (!response.ok) throw new Error("Could not load scripts");
    const data = await response.json();
    setScripts(data);
    setSelected((current) => current || data[0] || null);
  }

  async function generateScript(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/scripts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic,
          language,
          duration_seconds: Number(duration),
          niche: "Did You Know",
        }),
      });
      if (!response.ok) throw new Error("Generation failed");
      const script = await response.json();
      setSelected(script);
      await loadScripts();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadScripts().catch((err) => setError(err.message));
  }, []);

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Clapperboard size={24} />
          <span>AI Content Factory</span>
        </div>
        <form className="generator" onSubmit={generateScript}>
          <label>
            Topic
            <textarea value={topic} onChange={(event) => setTopic(event.target.value)} />
          </label>
          <label>
            Language
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              <option>English</option>
              <option>Greek</option>
              <option>Spanish</option>
              <option>German</option>
            </select>
          </label>
          <label>
            Duration: {duration}s
            <input
              type="range"
              min="15"
              max="180"
              step="15"
              value={duration}
              onChange={(event) => setDuration(event.target.value)}
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
            Generate Script
          </button>
          {error && <p className="error">{error}</p>}
        </form>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>Script Studio</h1>
            <p>Milestone 1: topic to saved video script.</p>
          </div>
          <button className="icon-button" onClick={() => loadScripts()} aria-label="Refresh scripts">
            <RefreshCw size={18} />
          </button>
        </header>

        <div className="content-grid">
          <section className="script-list">
            <h2>Recent Scripts</h2>
            {scripts.length === 0 && <p className="muted">No scripts yet.</p>}
            {scripts.map((script) => (
              <button
                className={selected?.id === script.id ? "script-row active" : "script-row"}
                key={script.id}
                onClick={() => setSelected(script)}
              >
                <strong>{script.title}</strong>
                <span>{new Date(script.created_at).toLocaleString()}</span>
              </button>
            ))}
          </section>

          <section className="script-detail">
            {selected ? (
              <>
                <div className="script-heading">
                  <h2>{selected.title}</h2>
                  <span>{selected.status}</span>
                </div>
                <p>{selected.description}</p>
                <div className="hashtags">{selected.hashtags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                <div className="scenes">
                  {selected.scenes.map((scene) => (
                    <article className="scene" key={scene.order}>
                      <div className="scene-number">{scene.order}</div>
                      <div>
                        <h3>Narration</h3>
                        <p>{scene.narration}</p>
                        <h3>Visual Prompt</h3>
                        <p>{scene.visual_prompt}</p>
                      </div>
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty-state">Generate a script to begin.</div>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
