"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";



function safeJsonParse(text) {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (e) {
    return { ok: false, error: e };
  }
}

function toUserFriendlyError(message, context) {
  const m = String(message || "");
  const lower = m.toLowerCase();

  if (
    lower.includes("failed to fetch") ||
    lower.includes("networkerror") ||
    lower.includes("load failed") ||
    lower.includes("connection refused") ||
    lower.includes("cors") ||
    lower.includes("typeerror: fetch")
  ) {
    return "Can't reach the server. Make sure the backend is running, then try again.";
  }

  if (lower.includes("invalid json body") || lower.includes("json decode error")) {
    return "Something went wrong while sending your request. Please try again.";
  }

  if (context === "upload") {
    if (lower.includes("please choose a pdf") || lower.includes("choose a pdf"))
      return "Please choose a PDF file to upload.";
    if (lower.includes("pdf")) return "Upload failed. Please try a different PDF or try again.";
    return "Upload failed. Please try again.";
  }

  if (context === "query") {
    if (lower.includes("question is empty")) return "Type a question to continue.";
    if (lower.includes("did you upload") || lower.includes("upload a pdf"))
      return "Please upload a PDF first, then ask your question.";
    return "I couldn't answer that. Please try again.";
  }

  return "Something went wrong. Please try again.";
}

function formatBytes(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}


function AuthView({ apiBase, onLogin }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  function switchMode(next) {
    setMode(next);
    setError("");
    setInfo("");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setInfo("");
    setLoading(true);
    try {
      if (mode === "signup") {
        const res = await fetch(`${apiBase}/auth/signup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, full_name: fullName }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data?.detail || "Signup failed.");
        setInfo(data.message || "Account created. Wait for admin activation.");
        switchMode("login");
      } else {
        const res = await fetch(`${apiBase}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data?.detail || "Login failed.");
        onLogin(data.access_token, data);
      }
    } catch (err) {
      const m = err?.message || "";
      if (m.toLowerCase().includes("pending")) {
        setError("Your account is pending activation. Contact an admin.");
      } else if (m.toLowerCase().includes("disabled")) {
        setError("Your account has been disabled. Contact an admin.");
      } else if (
        m.toLowerCase().includes("failed to fetch") ||
        m.toLowerCase().includes("load failed")
      ) {
        setError("Can't reach the server. Make sure the backend is running.");
      } else {
        setError(m || "Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <div className="auth-logo">RAG Chatbot</div>
        <p className="auth-subtitle">Multi-Modal Document Intelligence</p>

        <div className="auth-tabs">
          <button
            type="button"
            className={`auth-tab ${mode === "login" ? "active" : ""}`}
            onClick={() => switchMode("login")}
          >
            Login
          </button>
          <button
            type="button"
            className={`auth-tab ${mode === "signup" ? "active" : ""}`}
            onClick={() => switchMode("signup")}
          >
            Sign Up
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          {mode === "signup" && (
            <div className="field">
              <label className="field-label">Full Name</label>
              <input
                className="field-input"
                type="text"
                placeholder="Jane Doe"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
              />
            </div>
          )}
          <div className="field">
            <label className="field-label">Email</label>
            <input
              className="field-input"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label className="field-label">Password</label>
            <input
              className="field-input"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          {error && <div className="auth-error">{error}</div>}
          {info && <div className="auth-info">{info}</div>}

          <button className="auth-submit" type="submit" disabled={loading}>
            {loading ? "Please wait…" : mode === "login" ? "Login" : "Create Account"}
          </button>
        </form>

        {mode === "signup" && (
          <p className="auth-note">
            New accounts require admin activation before you can log in.
          </p>
        )}
      </div>
    </div>
  );
}



function ChatView({ apiBase, token, currentUser, onLogout }) {
  const fileRef = useRef(null);
  const messagesEndRef = useRef(null);

  const authHeaders = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  // Upload
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadSuccess, setUploadSuccess] = useState("");

  // Chat
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Click \"New Chat\" to start a session, then upload a PDF and ask questions." },
  ]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [sessionCreating, setSessionCreating] = useState(false);

  // Sessions
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);

  // Documents for the current session
  const [documents, setDocuments] = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    loadSessions();

  }, []);

  async function loadSessions() {
    setSessionsLoading(true);
    try {
      const res = await fetch(`${apiBase}/chat/sessions`, { headers: authHeaders });
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch {

    } finally {
      setSessionsLoading(false);
    }
  }

  async function downloadDocument(documentId, filename) {
    try {
      const res = await fetch(`${apiBase}/documents/${documentId}/file`, {
        headers: authHeaders,
      });
      if (!res.ok) throw new Error("Download failed.");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "document.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Download error:", err);
    }
  }

  async function deleteDocument(documentId) {
    if (!confirm("Delete this document? This cannot be undone.")) return;
    try {
      const res = await fetch(`${apiBase}/documents/${documentId}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (res.ok) {
        setDocuments((prev) => prev.filter((d) => d.document_id !== documentId));
      }
    } catch (err) {
      console.error("Delete error:", err);
    }
  }

  async function loadSessionDocuments(sessionId) {
    if (!sessionId) { setDocuments([]); return; }
    setDocsLoading(true);
    try {
      const res = await fetch(`${apiBase}/chat/sessions/${sessionId}/documents`, {
        headers: authHeaders,
      });
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
      }
    } catch {

    } finally {
      setDocsLoading(false);
    }
  }

  async function openSession(sessionId) {
    try {
      const res = await fetch(`${apiBase}/chat/sessions/${sessionId}`, {
        headers: authHeaders,
      });
      if (!res.ok) return;
      const data = await res.json();
      const msgs = (data.messages || []).map((m) => ({
        role: m.role,
        content: m.content,
      }));
      setMessages(
        msgs.length ? msgs : [{ role: "assistant", content: "No messages in this session yet. Upload a PDF to get started." }]
      );
      setCurrentSessionId(sessionId);
      setUploadError("");
      setUploadSuccess("");
      loadSessionDocuments(sessionId);
    } catch {

    }
  }

  async function deleteSession(sessionId, e) {
    e.stopPropagation();
    try {
      await fetch(`${apiBase}/chat/sessions/${sessionId}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null);
        setDocuments([]);
        setMessages([{ role: "assistant", content: "Click \"New Chat\" to start a session, then upload a PDF and ask questions." }]);
        setUploadError("");
        setUploadSuccess("");
      }
    } catch {

    }
  }

  async function newChat() {
    setSessionCreating(true);
    setUploadError("");
    setUploadSuccess("");
    setDocuments([]);
    try {
      const res = await fetch(`${apiBase}/chat/sessions`, {
        method: "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ title: "New Chat" }),
      });
      if (!res.ok) throw new Error("Failed to create session.");
      const data = await res.json();
      const newId = data.session?.session_id;
      setCurrentSessionId(newId);
      setMessages([{ role: "assistant", content: "Session ready. Upload a PDF and ask questions about it." }]);
      setSessions((prev) => [data.session, ...prev]);
    } catch {
      setMessages([{ role: "assistant", content: "Upload a PDF, then ask questions about it." }]);
      setCurrentSessionId(null);
    } finally {
      setSessionCreating(false);
    }
  }

  async function onUpload() {
    setUploadError("");
    setUploadSuccess("");

    if (!currentSessionId) {
      setUploadError("Start a new chat session first before uploading.");
      return;
    }

    const file = fileRef.current?.files?.[0];
    if (!file) {
      setUploadError("Please choose a PDF file.");
      return;
    }
    if (file.type && file.type !== "application/pdf") {
      setUploadError("Please upload a PDF file.");
      return;
    }

    const form = new FormData();
    form.append("file", file);
    form.append("session_id", currentSessionId);

    setUploading(true);
    try {
      const res = await fetch(`${apiBase}/upload`, {
        method: "POST",
        headers: authHeaders,
        body: form,
      });
      const text = await res.text();
      const parsed = safeJsonParse(text);

      if (!res.ok) {
        const detail = parsed.ok && parsed.value?.detail ? parsed.value.detail : text;
        throw new Error(detail || `Upload failed (${res.status})`);
      }

      setUploadSuccess(`"${file.name}" indexed successfully.`);
      if (fileRef.current) fileRef.current.value = "";
      loadSessionDocuments(currentSessionId);
    } catch (err) {
      console.error("Upload error:", err);
      setUploadError(toUserFriendlyError(err?.message || err, "upload"));
    } finally {
      setUploading(false);
    }
  }

  async function onSend(e) {
    e?.preventDefault?.();
    if (uploading || sending) return;
    const q = question.trim();
    if (!q) return;

    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setQuestion("");
    setSending(true);

    try {
      const res = await fetch(`${apiBase}/query`, {
        method: "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, session_id: currentSessionId }),
      });
      const text = await res.text();
      const parsed = safeJsonParse(text);

      if (!res.ok) {
        const detail = parsed.ok && parsed.value?.detail ? parsed.value.detail : text;
        throw new Error(detail || `Query failed (${res.status})`);
      }

      const answer = parsed.ok ? parsed.value?.answer : text;
      const images = parsed.ok ? parsed.value?.images || [] : [];
      const returnedSessionId = parsed.ok ? parsed.value?.meta?.session_id : null;

      if (returnedSessionId && !currentSessionId) {
        setCurrentSessionId(returnedSessionId);
        loadSessions();
      }

      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: answer || "(empty response)", images },
      ]);
    } catch (err) {
      console.error("Query error:", err);
      const friendly = toUserFriendlyError(err?.message || err, "query");
      setMessages((prev) => [...prev, { role: "assistant", content: friendly }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="app-container">

      <aside className="sidebar">
        <div className="sidebar-header">
          <h1 className="app-title">RAG Chatbot</h1>
          <div className="user-row">
            <span className="user-email" title={currentUser?.email}>
              {currentUser?.email}
            </span>
            <button className="logout-btn" onClick={onLogout}>
              Logout
            </button>
          </div>
        </div>

        <div className="sidebar-content">

          <button
            className="btn btn-new-chat"
            onClick={newChat}
            disabled={sessionCreating}
          >
            {sessionCreating ? "Creating…" : "+ New Chat"}
          </button>

   
          <div className="section-label">Recent Chats</div>
          <div className="sessions-list">
            {sessionsLoading && <div className="list-placeholder">Loading…</div>}
            {!sessionsLoading && sessions.length === 0 && (
              <div className="list-placeholder">No chats yet.</div>
            )}
            {sessions.map((s) => (
              <div
                key={s.session_id}
                className={`session-item ${currentSessionId === s.session_id ? "session-active" : ""}`}
                onClick={() => openSession(s.session_id)}
              >
                <span className="session-title">{s.title || "Untitled"}</span>
                <button
                  className="session-delete"
                  title="Delete session"
                  onClick={(ev) => deleteSession(s.session_id, ev)}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>

        
          <div className="section-label" style={{ marginTop: 8 }}>
            Upload Document
          </div>
          {!currentSessionId ? (
            <div className="status-msg status-info">
              Start a new chat to upload a document.
            </div>
          ) : (
            <div className="upload-section">
              <div className="session-badge">
                Session active
              </div>
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
                  {uploading ? "Uploading…" : "Upload PDF"}
                </button>
              </div>
              {uploadError && (
                <div className="status-msg status-error">{uploadError}</div>
              )}
              {uploadSuccess && (
                <div className="status-msg status-success">{uploadSuccess}</div>
              )}
            </div>
          )}

    
          {currentSessionId && (
            <>
              <div className="section-label">Session Documents</div>
              <div className="docs-list">
                {docsLoading && <div className="list-placeholder">Loading…</div>}
                {!docsLoading && documents.length === 0 && (
                  <div className="list-placeholder">No documents uploaded to this session.</div>
                )}
                {documents.map((d) => (
                  <div key={d.document_id} className="doc-item">
                    <div className="doc-info">
                      <span className="doc-name" title={d.filename}>
                        {d.filename}
                      </span>
                      <span className="doc-size">{formatBytes(d.file_size_bytes)}</span>
                    </div>
                    <div className="doc-actions">
                      {d.has_file && (
                        <button
                          className="doc-btn doc-btn-download"
                          title="Download PDF"
                          onClick={() => downloadDocument(d.document_id, d.filename)}
                        >
                          ↓
                        </button>
                      )}
                      <button
                        className="doc-btn doc-btn-delete"
                        title="Delete document"
                        onClick={() => deleteDocument(d.document_id)}
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </aside>

  
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
                {m.role === "assistant" ? (
                  <div className="md">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        a: ({ node, ...props }) => (
                          <a {...props} target="_blank" rel="noreferrer" />
                        ),
                      }}
                    >
                      {m.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <span className="plain">{m.content}</span>
                )}
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
                      alt={`Image ${i + 1}`}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div className="composer-container">
          <form className="composer-form" onSubmit={onSend}>
            <input
              className="composer-input"
              value={question}
              placeholder={uploading ? "Uploading…" : "Message…"}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={sending || uploading}
            />
            <button
              className="btn-send"
              type="submit"
              disabled={sending || uploading}
            >
              {uploading ? "Uploading…" : sending ? "…" : "Send"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}



export default function HomePage() {
  const apiBase = useMemo(
    () => process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000",
    []
  );

  const [token, setToken] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);


  useEffect(() => {
    const saved =
      typeof window !== "undefined" ? localStorage.getItem("rag_token") : null;
    if (!saved) {
      setAuthLoading(false);
      return;
    }
    fetch(`${apiBase}/auth/me`, {
      headers: { Authorization: `Bearer ${saved}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.user_id || data?.email) {
          setToken(saved);
          setCurrentUser(data);
        } else {
          localStorage.removeItem("rag_token");
        }
      })
      .catch(() => localStorage.removeItem("rag_token"))
      .finally(() => setAuthLoading(false));
  }, [apiBase]);

  function handleLogin(newToken, userData) {
    localStorage.setItem("rag_token", newToken);
    setToken(newToken);
    setCurrentUser(userData);
  }

  function handleLogout() {
    localStorage.removeItem("rag_token");
    setToken(null);
    setCurrentUser(null);
  }

  if (authLoading) {
    return (
      <div className="loading-screen">
        <div className="loading-spinner" />
      </div>
    );
  }

  if (!token) {
    return <AuthView apiBase={apiBase} onLogin={handleLogin} />;
  }

  return (
    <ChatView
      apiBase={apiBase}
      token={token}
      currentUser={currentUser}
      onLogout={handleLogout}
    />
  );
}
