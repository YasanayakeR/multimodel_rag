"use client";

import { useMemo, useRef, useState } from "react";

function safeJsonParse(text) {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (e) {
    return { ok: false, error: e };
  }
}

export default function HomePage() {
  const apiBase = useMemo(
    () => process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000",
    []
  );

  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [uploadInfo, setUploadInfo] = useState(null);
  const [uploadError, setUploadError] = useState("");

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Upload a PDF first, then ask questions. If your PDF contains images, relevant image snippets may appear below answers.",
    },
  ]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [queryError, setQueryError] = useState("");

  async function onUpload() {
    setUploadError("");
    setUploadInfo(null);

    const file = fileRef.current?.files?.[0];
    if (!file) {
      setUploadError("Please choose a PDF file.");
      return;
    }
    if (file.type && file.type !== "application/pdf") {
      setUploadError("Please upload a PDF (application/pdf).");
      return;
    }

    const form = new FormData();
    form.append("file", file);

    setUploading(true);
    try {
      const res = await fetch(`${apiBase}/upload`, {
        method: "POST",
        body: form,
      });

      const text = await res.text();
      const parsed = safeJsonParse(text);

      if (!res.ok) {
        const detail =
          parsed.ok && parsed.value?.detail ? parsed.value.detail : text;
        throw new Error(detail || `Upload failed (${res.status})`);
      }

      setUploadInfo(parsed.ok ? parsed.value : { raw: text });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `PDF indexed successfully.${parsed.ok && parsed.value?.counts
            ? ` (texts: ${parsed.value.counts.texts}, tables: ${parsed.value.counts.tables}, images: ${parsed.value.counts.images})`
            : ""
            }`,
        },
      ]);
    } catch (e) {
      setUploadError(String(e?.message || e));
    } finally {
      setUploading(false);
    }
  }

  async function onSend(e) {
    e?.preventDefault?.();
    setQueryError("");
    const q = question.trim();
    if (!q) return;

    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setQuestion("");
    setSending(true);

    try {
      const res = await fetch(`${apiBase}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });

      const text = await res.text();
      const parsed = safeJsonParse(text);

      if (!res.ok) {
        const detail =
          parsed.ok && parsed.value?.detail ? parsed.value.detail : text;
        throw new Error(detail || `Query failed (${res.status})`);
      }

      const answer = parsed.ok ? parsed.value?.answer : text;
      const images = parsed.ok ? parsed.value?.images || [] : [];

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: answer || "(empty response)",
          images,
        },
      ]);
    } catch (e) {
      const msg = String(e?.message || e);
      setQueryError(msg);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Error: ${msg}`,
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="app-container">
      {/* Sidebar: Upload & Controls */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1 className="app-title">RAG Chatbot</h1>
        </div>

        <div className="sidebar-content">
          <div className="upload-section">
            <div className="section-label">Source Document</div>
            <div className="file-input-wrapper">
              <input
                ref={fileRef}
                className="file-input"
                type="file"
                accept=".pdf,application/pdf"
                title="Select a PDF file"
              />
            </div>

            <div className="actions">
              <button
                className="btn btn-primary"
                onClick={onUpload}
                disabled={uploading}
              >
                {uploading ? "Uploading..." : "Upload PDF"}
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setUploadError("");
                  setUploadInfo(null);
                  if (fileRef.current) fileRef.current.value = "";
                }}
                disabled={uploading}
              >
                Clear
              </button>
            </div>

            {uploadError && (
              <div className="status-msg status-error">
                {uploadError}
              </div>
            )}

            {uploadInfo && (
              <div className="status-msg status-success">
                Index complete. Ready to chat!
              </div>
            )}
          </div>
        </div>

        <div className="sidebar-footer">
        </div>
      </aside>

      {/* Main Chat Area */}
      <main className="main-chat">
        <div className="messages-container">
          {messages.map((m, idx) => (
            <div className="message-wrapper" key={idx}>
              <div
                className={[
                  "message-bubble",
                  m.role === "user" ? "message-user" : "message-assistant",
                ].join(" ")}
              >
                {m.content}
              </div>

              {Array.isArray(m.images) && m.images.length ? (
                <div
                  className="image-grid"
                  style={{
                    marginLeft: m.role === "user" ? "auto" : 0,
                    marginRight: m.role === "user" ? 0 : "auto",
                  }}
                >
                  {m.images.slice(0, 6).map((b64, i) => (
                    <img
                      key={i}
                      className="image-item"
                      src={`data:image/jpeg;base64,${b64}`}
                      alt={`Retrieved image ${i + 1}`}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          ))}

          {queryError && (
            <div className="message-wrapper">
              <div className="status-msg status-error" style={{ width: "fit-content" }}>
                Error: {queryError}
              </div>
            </div>
          )}
        </div>

        <div className="composer-container">
          <form className="composer-form" onSubmit={onSend}>
            <input
              className="composer-input"
              value={question}
              placeholder="Message..."
              onChange={(e) => setQuestion(e.target.value)}
              disabled={sending}
            />
            <button className="btn-send" type="submit" disabled={sending}>
              {sending ? "..." : "Send"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}

