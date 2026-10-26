import React, { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  ChevronDown,
  FlaskConical,
  Info,
  LoaderCircle,
  MessageSquare,
  Plus,
  SlidersHorizontal,
  Square,
  X,
  ArrowUpRight,
} from "lucide-react";

const INTENTS = {
  auto: "Tự động · chat mặc định",
  chat: "Chỉ chat",
  research: "Research Lab",
};

export default function Conversation({
  api,
  Md,
  modes,
  id,
  onSelect,
  onChanged,
  onOpenLab,
  config,
}) {
  const [conversation, setConversation] = useState(null);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState("demo");
  const [intent, setIntent] = useState("auto");
  const [budget, setBudget] = useState(0.75);
  const [notes, setNotes] = useState("");
  const [revisions, setRevisions] = useState(1);
  const [followup, setFollowup] = useState(true);
  const [files, setFiles] = useState([]);
  const [options, setOptions] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const alive = useRef(true),
    sending = useRef(false),
    bottom = useRef(null);
  const callbacks = useRef({ onChanged });
  callbacks.current = { onChanged };
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!id) return;
    api(`/conversations/${id}`)
      .then((c) => {
        if (!alive.current) return;
        setConversation(c);
        setMode(c.mode);
        setBudget(c.budget);
        setIntent(c.default_intent || "auto");
      })
      .catch((e) => {
        if (alive.current) setError(e.message);
      });
  }, [id, api]);
  const responding = conversation?.status === "responding";
  const sessionId = id || conversation?.id;
  const lastStatus = conversation?.messages?.at(-1)?.status;
  useEffect(() => {
    if (!sessionId) return;
    let fetching = false;
    const timer = setInterval(
      async () => {
        if (fetching) return;
        fetching = true;
        try {
          const c = await api(`/conversations/${sessionId}`);
          if (alive.current) {
            setConversation(c);
            if (responding && c.status !== "responding")
              callbacks.current.onChanged();
          }
        } catch (e) {
          if (alive.current) setError(e.message);
        } finally {
          fetching = false;
        }
      },
      responding ? 900 : 3000,
    );
    return () => clearInterval(timer);
  }, [sessionId, responding, api]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [conversation?.messages?.length, lastStatus]);

  async function upload(conversationId, file) {
    if (file.size > 10000000) throw new Error("Mỗi file tối đa 10 MB.");
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192)
      binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return api(`/runs/${conversationId}/documents`, {
      method: "POST",
      body: JSON.stringify({ name: file.name, content_base64: btoa(binary) }),
    });
  }
  async function send(e) {
    e?.preventDefault();
    if (!input.trim() || sending.current || responding || (id && !conversation))
      return;
    sending.current = true;
    setBusy(true);
    setError("");
    let target = id || conversation?.id;
    try {
      if (!target) {
        const c = await api("/conversations", {
          method: "POST",
          body: JSON.stringify({ mode, budget: Number(budget) }),
        });
        target = c.id;
      }
      for (const file of files) await upload(target, file);
      const c = await api(`/conversations/${target}/messages`, {
        method: "POST",
        body: JSON.stringify({
          content: input.trim(),
          intent,
          mode,
          budget: Number(budget),
          notes,
          max_revisions: revisions,
          followup,
        }),
      });
      if (!alive.current) return;
      setConversation(c);
      setIntent(c.default_intent || "auto");
      setInput("");
      setFiles([]);
      callbacks.current.onChanged();
      if (!id) onSelect(target);
    } catch (e) {
      if (alive.current) {
        setError(e.message);
        // Keep this component mounted so unsent text/files survive an API error.
        if (target && !id) {
          setConversation(
            await api(`/conversations/${target}`).catch(() => null),
          );
        }
      }
    } finally {
      sending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function stop() {
    setError("");
    try {
      await api(`/conversations/${sessionId}/stop`, { method: "POST" });
      setConversation(await api(`/conversations/${sessionId}`));
      callbacks.current.onChanged();
    } catch (e) {
      setError(e.message);
    }
  }
  const messages = conversation?.messages || [];
  const chatRoute = config?.routes?.[mode]?.find((r) => r.role === "intake");
  return (
    <div className={"chat-space " + (messages.length ? "has-messages" : "")}>
      {id && !conversation ? (
        <div className="chat-loading">
          <LoaderCircle size={22} className="spin" />
          <span>Đang mở hội thoại…</span>
        </div>
      ) : !messages.length ? (
        <div className="welcome chat-welcome">
          <div className="welcome-eyebrow">AGENTLABS · PERSONAL ASSISTANT</div>
          <div className="chat-hero-icon">
            <MessageSquare size={33} strokeWidth={1.4} />
          </div>
          <h1>
            Bắt đầu bằng
            <br />
            <span>một cuộc trò chuyện.</span>
          </h1>
          <p>
            Hỏi, giải thích code, trao đổi ý tưởng, chỉnh văn bản.
            <br />
            Research Lab chỉ chạy khi bạn giao nhiệm vụ nghiên cứu.
          </p>
          <div className="welcome-pills">
            <span>
              <MessageSquare size={13} /> Chat mặc định
            </span>
            <span>
              <FlaskConical size={13} /> Lab khi bạn yêu cầu
            </span>
          </div>
        </div>
      ) : (
        <div className="conversation regular-conversation" aria-live="polite">
          <div className="chat-session-title">
            <span>{conversation.topic}</span>
            <small>
              {Number(conversation.spend || 0).toFixed(3)} / $
              {conversation.budget} · USD
            </small>
          </div>
          {messages.map((m) => {
            const lab = conversation.linked_runs?.find(
              (r) => r.id === m.run_id,
            );
            return (
              <article className={`chat-message ${m.role}`} key={m.id}>
                <div className="chat-author">
                  {m.role === "user" ? "Bạn" : "AgentLabs"}
                  {m.role === "assistant" && (
                    <small>
                      {m.run_id ? "Research Lab" : m.model || "Chat"}
                    </small>
                  )}
                </div>
                {m.status === "pending" ? (
                  <div className="working">
                    <LoaderCircle size={15} className="spin" />
                    <span>Đang trả lời…</span>
                  </div>
                ) : (
                  <Md>{m.content}</Md>
                )}
                {["error", "interrupted"].includes(m.status) && (
                  <small className="chat-error-note">
                    Chưa hoàn tất · bạn có thể gửi lại hoặc đổi provider.
                  </small>
                )}
                {m.run_id && (
                  <button
                    className="lab-link-card"
                    onClick={() => onOpenLab(m.run_id)}
                  >
                    <FlaskConical size={21} />
                    <span>
                      <strong>{lab?.topic || "Nhiệm vụ nghiên cứu"}</strong>
                      <small>
                        {lab?.status === "waiting"
                          ? "Đang chờ bạn duyệt"
                          : lab?.status === "running"
                            ? "Các agent đang làm việc"
                            : lab?.status === "error"
                              ? "Cần kiểm tra lỗi trong lab"
                              : "Xem tiến trình, artifacts và review"}
                      </small>
                    </span>
                    <span>
                      Mở lab <ArrowUpRight size={14} />
                    </span>
                  </button>
                )}
              </article>
            );
          })}
          {conversation.context_truncated && (
            <p className="chat-context-note">
              Lịch sử vẫn lưu đầy đủ trên máy. Model chỉ nhận các lượt gần nhất
              trong giới hạn 32.000 ký tự / 40 tin nhắn.
            </p>
          )}
          <div ref={bottom} />
        </div>
      )}
      <div
        className={`composer-area chat-composer ${!messages.length ? "centered" : ""}`}
      >
        {error && (
          <div className="notice warning" role="alert">
            <Info size={15} />
            {error}
          </div>
        )}
        <div className="intent-row">
          <label>
            Gửi đến{" "}
            <select
              aria-label="Cách xử lý tin nhắn"
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
            >
              {Object.entries(INTENTS).map(([key, label]) => (
                <option value={key} key={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <span>
            {intent === "research"
              ? "Chạy đội ngũ nghiên cứu"
              : intent === "chat"
                ? "Luôn trả lời trực tiếp; /research vẫn có hiệu lực"
                : "Chat mặc định · giao nghiên cứu rõ ràng → lab"}
          </span>
        </div>
        <form className="composer" onSubmit={send}>
          <textarea
            aria-label="Tin nhắn"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                send(e);
              }
            }}
            placeholder={
              intent === "research"
                ? "Giao nhiệm vụ nghiên cứu cho lab…"
                : "Nhắn AgentLabs… hoặc /research để giao nghiên cứu"
            }
            rows={2}
            maxLength={8000}
          />
          <div className="upload-line">
            <label className="attach-label">
              <Plus size={12} />
              <span>Thêm tài liệu</span>
              <input
                type="file"
                accept=".pdf,.txt,.md,.csv,.json"
                multiple
                disabled={busy || responding}
                onChange={(e) => {
                  setFiles(Array.from(e.target.files).slice(0, 5));
                  e.target.value = "";
                }}
              />
            </label>
            {files.map((f, i) => (
              <button
                type="button"
                key={i}
                onClick={() => setFiles(files.filter((_, j) => j !== i))}
              >
                {f.name}
                <X size={11} />
              </button>
            ))}
          </div>
          <div className="composer-tools">
            <div>
              <button
                type="button"
                className="icon-btn"
                aria-label="Tùy chọn hội thoại"
                title="Tùy chọn hội thoại"
                onClick={() => setOptions(!options)}
              >
                <SlidersHorizontal size={17} />
              </button>
              <span className="mode-select">
                <select
                  aria-label="Provider hội thoại"
                  value={mode}
                  disabled={busy || responding}
                  onChange={(e) => {
                    setMode(e.target.value);
                    if (e.target.value === "openclaw") setBudget(2);
                  }}
                >
                  {Object.entries(modes).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
                <ChevronDown size={13} />
              </span>
            </div>
            {responding ? (
              <button
                type="button"
                className="send-btn"
                aria-label="Dừng trả lời"
                title="Dừng trả lời"
                onClick={stop}
              >
                <Square size={15} fill="currentColor" />
              </button>
            ) : (
              <button
                className="send-btn"
                type="submit"
                aria-label="Gửi tin nhắn"
                title="Gửi tin nhắn"
                disabled={busy || !input.trim() || (id && !conversation)}
              >
                {busy ? (
                  <LoaderCircle size={18} className="spin" />
                ) : (
                  <ArrowUp size={20} />
                )}
              </button>
            )}
          </div>
          {options && (
            <div className="composer-extra">
              <label>
                Giới hạn USD cho hội thoại / mỗi workflow mới
                <input
                  type="number"
                  min="0.05"
                  max="20"
                  step="0.05"
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                />
              </label>
              <label>
                Ghi chú cho nhiệm vụ Research Lab
                <textarea
                  rows={2}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Dataset, baseline, compute budget…"
                  maxLength={12000}
                />
              </label>
              <label>
                Vòng sửa tối đa trong Research Lab
                <select
                  value={revisions}
                  onChange={(e) => setRevisions(Number(e.target.value))}
                >
                  <option value={0}>0 · chỉ review</option>
                  <option value={1}>1 · một vòng sửa</option>
                </select>
              </label>
              {conversation?.latest_run_id && (
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={followup}
                    onChange={(e) => setFollowup(e.target.checked)}
                  />
                  Kế thừa nghiên cứu gần nhất khi giao nhiệm vụ lab tiếp theo
                </label>
              )}
            </div>
          )}
        </form>
        <p className="composer-foot">
          <Info size={12} />
          {mode === "demo"
            ? "Demo là phản hồi mẫu, không gọi model. Chọn provider có key để chat thật."
            : `Chat dùng ${chatRoute?.model || "model tiết kiệm"}. Lịch sử/snippets cần thiết được gửi tới provider đã chọn.`}
        </p>
        {!!conversation?.documents?.length && (
          <p className="chat-context-note">
            {conversation.documents.length} tài liệu đã nhập vào hội thoại ·
            tools chỉ đọc.
          </p>
        )}
        {!messages.length && (
          <div className="suggestions">
            {[
              [
                MessageSquare,
                "Giải thích một khái niệm",
                "Giải thích overfitting bằng một ví dụ dễ hiểu.",
              ],
              [
                Info,
                "Trao đổi ý tưởng",
                "Tôi đang tìm hiểu RAG. Hãy cùng tôi thảo luận ưu nhược điểm.",
              ],
              [
                FlaskConical,
                "Giao nhiệm vụ cho Research Lab",
                "/research Thiết kế thực nghiệm so sánh hai baseline RAG với cùng compute budget.",
              ],
            ].map(([Icon, title, text]) => (
              <button key={title} onClick={() => setInput(text)}>
                <Icon size={18} />
                <span>{title}</span>
                <ArrowUpRight size={14} />
              </button>
            ))}
          </div>
        )}
        {sessionId && (
          <p className="chat-context-note">
            Hội thoại tự lưu trên máy · Enter gửi · Shift+Enter xuống dòng
          </p>
        )}
      </div>
    </div>
  );
}
