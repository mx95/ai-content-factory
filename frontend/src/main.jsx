import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  Clapperboard,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  X,
} from "lucide-react";
import "./styles.css";

const API_BASE = "/api";

function App() {
  const [topic, setTopic] = useState("Why do octopuses have three hearts?");
  const [language, setLanguage] = useState("English");
  const [duration, setDuration] = useState(45);
  const [scripts, setScripts] = useState([]);
  const [selected, setSelected] = useState(null);
  const [video, setVideo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState("");
  const [error, setError] = useState("");

  async function loadScripts(preferredId = null) {
    const response = await fetch(`${API_BASE}/scripts`);
    if (!response.ok) throw new Error("Could not load scripts");
    const data = await response.json();
    setScripts(data);
    setSelected((current) => {
      if (preferredId) {
        return data.find((item) => item.id === preferredId) || data[0] || null;
      }
      if (current) {
        return data.find((item) => item.id === current.id) || data[0] || null;
      }
      return data[0] || null;
    });
  }

  async function loadVideo(videoId) {
    if (!videoId) {
      setVideo(null);
      return;
    }
    const response = await fetch(`${API_BASE}/videos/${videoId}`);
    if (!response.ok) throw new Error("Could not load video job");
    const data = await response.json();
    setVideo(data);
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
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Generation failed");
      }
      const script = await response.json();
      await loadScripts(script.id);
      if (script.video_id) {
        await loadVideo(script.video_id);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function runVideoAction(action) {
    if (!video?.id) return;
    setActionLoading(action);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/videos/${video.id}/${action}`, {
        method: "POST",
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || `${action} failed`);
      }
      const data = await response.json();
      setVideo(data);
      await loadScripts(selected?.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  }

  useEffect(() => {
    loadScripts().catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!selected?.video_id) {
      setVideo(null);
      return;
    }
    loadVideo(selected.video_id).catch((err) => setError(err.message));
  }, [selected?.id, selected?.video_id]);

  useEffect(() => {
    if (!video?.id) return undefined;
    if (!["queued", "rendering"].includes(video.status)) return undefined;
    const timer = setInterval(() => {
      loadVideo(video.id).catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [video?.id, video?.status]);

  const isBusy = video && ["queued", "rendering"].includes(video.status);
  const isReady = video?.status === "ready";
  const videoUrl = video?.id ? `${API_BASE}/media/${video.id}/final.mp4` : null;
  const thumbUrl = video?.id ? `${API_BASE}/media/${video.id}/thumb.png` : null;

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
            Generate & Render
          </button>
          {error && <p className="error">{error}</p>}
        </form>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>Video Studio</h1>
            <p>Script → voice → images → captions → MP4 → approve.</p>
          </div>
          <button
            className="icon-button"
            onClick={() => loadScripts(selected?.id).catch((err) => setError(err.message))}
            aria-label="Refresh"
          >
            <RefreshCw size={18} />
          </button>
        </header>

        <div className="content-grid">
          <section className="script-list">
            <h2>Recent Jobs</h2>
            {scripts.length === 0 && <p className="muted">No jobs yet.</p>}
            {scripts.map((script) => (
              <button
                className={selected?.id === script.id ? "script-row active" : "script-row"}
                key={script.id}
                onClick={() => setSelected(script)}
              >
                <strong>{script.title}</strong>
                <span>
                  {script.video_status || script.status} · {new Date(script.created_at).toLocaleString()}
                </span>
              </button>
            ))}
          </section>

          <section className="script-detail">
            {selected ? (
              <>
                <div className="script-heading">
                  <h2>{selected.title}</h2>
                  <span>{video?.status || selected.video_status || selected.status}</span>
                </div>
                <p>{selected.description}</p>
                <div className="hashtags">
                  {selected.hashtags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>

                <div className="pipeline-panel">
                  <h3>Render pipeline</h3>
                  {isBusy && (
                    <p className="pipeline-status">
                      <Loader2 className="spin" size={16} /> Rendering video… this can take a few minutes.
                    </p>
                  )}
                  {video?.status === "failed" && (
                    <p className="pipeline-error">{video.error || "Render failed"}</p>
                  )}
                  {(isReady || video?.status === "approved" || video?.status === "rejected") && videoUrl && (
                    <div className="preview-block">
                      {thumbUrl && <img className="thumb" src={thumbUrl} alt="Thumbnail" />}
                      <video className="preview-video" src={videoUrl} controls playsInline poster={thumbUrl || undefined} />
                      <div className="action-row">
                        {isReady && (
                          <>
                            <button
                              className="action approve"
                              disabled={!!actionLoading}
                              onClick={() => runVideoAction("approve")}
                            >
                              {actionLoading === "approve" ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
                              Approve
                            </button>
                            <button
                              className="action reject"
                              disabled={!!actionLoading}
                              onClick={() => runVideoAction("reject")}
                            >
                              {actionLoading === "reject" ? <Loader2 className="spin" size={16} /> : <X size={16} />}
                              Reject
                            </button>
                          </>
                        )}
                        <button
                          className="action regenerate"
                          disabled={!!actionLoading || isBusy}
                          onClick={() => runVideoAction("render")}
                        >
                          {actionLoading === "render" ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
                          Regenerate
                        </button>
                      </div>
                      {video?.status === "approved" && (
                        <p className="pipeline-ok">Approved. YouTube upload comes in the next build.</p>
                      )}
                      {video?.status === "rejected" && (
                        <p className="pipeline-error">Rejected. Regenerate to try again.</p>
                      )}
                    </div>
                  )}
                </div>

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
