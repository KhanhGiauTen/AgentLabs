import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Plus,
  MessageSquare,
  Library,
  Users,
  FlaskConical,
  FileText,
  SlidersHorizontal,
  ArrowUp,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Check,
  Circle,
  LoaderCircle,
  Download,
  Pause,
  Play,
  X,
  ShieldCheck,
  Wallet,
  ExternalLink,
  ArrowRight,
  BookOpen,
  GitBranch,
  FolderOpen,
  Terminal,
  RefreshCw,
  Copy,
  CheckCheck,
  Info,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Conversation from "./Conversation";
import "./style.css";

const MODES = {
  demo: "Demo · không tốn phí",
  lean: "Lean · Luna + Sol",
  hybrid: "Hybrid · Free + Sol",
  free: "Free · OpenRouter",
  local: "Local · Ollama",
  claude: "Claude · Sonnet + Opus",
  openclaw: "OpenClaw · local harness",
};
const STATUS = {
  draft: "Chờ bắt đầu",
  running: "Đang nghiên cứu",
  waiting: "Chờ bạn xem xét",
  completed: "Hoàn tất bản nháp",
  error: "Cần xử lý",
  interrupted: "Đã tạm dừng",
};
const NAV = [
  { id: "talk", label: "Trò chuyện", icon: MessageSquare },
  { id: "chat", label: "Research Lab", icon: FlaskConical },
  { id: "library", label: "Tài liệu & bằng chứng", icon: Library },
  { id: "agents", label: "Đội ngũ nghiên cứu", icon: Users },
  { id: "experiments", label: "Thực nghiệm", icon: FlaskConical },
  { id: "reviews", label: "Hội đồng review", icon: ShieldCheck },
  { id: "paper", label: "Bản thảo paper", icon: FileText },
];
const money = (x) => "$" + Number(x || 0).toFixed(3);
async function api(path, options = {}) {
  const r = await fetch("/api" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Studio-Client": "local-ui",
      ...options.headers,
    },
  });
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      Array.isArray(data.detail)
        ? data.detail.map((e) => e.msg).join("; ")
        : data.detail || "Không thể kết nối",
    );
  return data;
}
function Mark({ size = 36 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      {Array.from({ length: 12 }, (_, i) => (
        <path
          key={i}
          d="M24 5 L24 15"
          stroke="currentColor"
          strokeWidth={i % 2 ? 3 : 4}
          strokeLinecap="round"
          transform={`rotate(${i * 30} 24 24)`}
        />
      ))}
      <circle cx="24" cy="24" r="5" fill="currentColor" />
    </svg>
  );
}
function Md({ children }) {
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
          img: () => null,
        }}
      >
        {children || ""}
      </Markdown>
    </div>
  );
}
function Badge({ children, tone = "" }) {
  return <span className={"badge " + tone}>{children}</span>;
}

function App() {
  const [config, setConfig] = useState(null),
    [runs, setRuns] = useState([]),
    [run, setRun] = useState(null),
    [selected, setSelected] = useState(localStorage.getItem("studio-run")),
    [view, setView] = useState("talk"),
    [conversationId, setConversationId] = useState(
      localStorage.getItem("studio-conversation") || null,
    ),
    [conversations, setConversations] = useState([]),
    [draftSequence, setDraftSequence] = useState(0);
  const [input, setInput] = useState(""),
    [mode, setMode] = useState("demo"),
    [budget, setBudget] = useState(0.75),
    [notes, setNotes] = useState(""),
    [showNotes, setShowNotes] = useState(false),
    [usage, setUsage] = useState(null),
    [health, setHealth] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [sidebar, setSidebar] = useState(true),
    [preview, setPreview] = useState(null);
  const [query, setQuery] = useState(""),
    [source, setSource] = useState("crossref"),
    [papers, setPapers] = useState([]),
    [searching, setSearching] = useState(false),
    [searchSaved, setSearchSaved] = useState(false),
    [monthly, setMonthly] = useState(15),
    [calls, setCalls] = useState(20),
    [copied, setCopied] = useState(false),
    [followup, setFollowup] = useState(false);
  const [attachments, setAttachments] = useState([]),
    [maxRevisions, setMaxRevisions] = useState(1);
  async function upload(id, file) {
    if (file.size > 10000000) throw new Error("Tài liệu tối đa 10 MB");
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192)
      binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return api(`/runs/${id}/documents`, {
      method: "POST",
      body: JSON.stringify({ name: file.name, content_base64: btoa(binary) }),
    });
  }
  async function refresh(id = selected) {
    try {
      const [list, u, chats] = await Promise.all([
        api("/runs"),
        api("/usage"),
        api("/conversations"),
      ]);
      setRuns(list);
      setUsage(u);
      setConversations(chats);
      if (id) setRun(await api("/runs/" + id));
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => {
    api("/config")
      .then((c) => {
        setConfig(c);
        setMonthly(c.settings.monthly_budget);
      })
      .catch((e) => setError(e.message));
    api("/health")
      .then(setHealth)
      .catch(() => {});
    refresh();
  }, []);
  useEffect(() => {
    localStorage.setItem("studio-conversation", conversationId || "");
  }, [conversationId]);
  useEffect(() => {
    localStorage.setItem("studio-run", selected || "");
    setPreview(null);
    setPapers([]);
    setFollowup(false);
    if (selected) {
      setRun(null);
      refresh(selected);
    } else setRun(null);
  }, [selected]);
  useEffect(() => {
    const t = setInterval(
      () => refresh(selected),
      run?.status === "running" ? 1200 : 5000,
    );
    return () => clearInterval(t);
  }, [selected, run?.status]);
  async function action(fn) {
    setError("");
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function start(e) {
    e?.preventDefault();
    if (input.trim().length < 5) {
      setError("Nhập câu hỏi nghiên cứu ít nhất 5 ký tự.");
      return;
    }
    await action(async () => {
      const r = await api("/runs", {
        method: "POST",
        body: JSON.stringify({
          topic: input.trim(),
          mode,
          budget: Number(budget),
          notes,
          max_revisions: maxRevisions,
          parent_id: followup ? selected : null,
          autostart: !attachments.length,
        }),
      });
      setSelected(r.id);
      setRun(r);
      setView("chat");
      if (attachments.length) {
        for (const f of attachments) await upload(r.id, f);
        await api(`/runs/${r.id}/resume`, { method: "POST" });
      }
      setAttachments([]);
      setInput("");
    });
  }
  function decide(a) {
    action(() =>
      api(`/runs/${selected}/decision`, {
        method: "POST",
        body: JSON.stringify({ action: a, sha256: run?.experiment?.sha256 }),
      }),
    );
  }
  async function search(e) {
    e.preventDefault();
    setSearching(true);
    setError("");
    try {
      const r = await api("/search", {
        method: "POST",
        body: JSON.stringify({ query, source, run_id: selected || null }),
      });
      setPapers(r.papers);
      setSearchSaved(r.persisted);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setSearching(false);
    }
  }
  async function artifact(name) {
    setError("");
    try {
      const r = await fetch(
        `/api/runs/${selected}/artifacts/${encodeURIComponent(name)}`,
      );
      if (!r.ok) throw new Error("Không đọc được artifact");
      if (name.match(/\.(png)$/i)) {
        setPreview({ name, image: true });
      } else setPreview({ name, content: (await r.text()).slice(0, 150000) });
    } catch (e) {
      setError(e.message);
    }
  }
  const roleFor = (id) => config?.roles.find((r) => r.id === id);
  const active = run?.status === "running";
  const currentSources = papers.length ? papers : run?.sources || [];
  const stagesDone = Object.keys(run?.outputs || {}).length;
  const currentMode = run?.mode || mode;

  return (
    <div className={"app " + (!sidebar ? "collapsed" : "")}>
      {sidebar && (
        <aside className="sidebar">
          <button
            className="brand"
            onClick={() => {
              setConversationId(null);
              setDraftSequence((n) => n + 1);
              setView("talk");
            }}
          >
            <span className="brand-mark">
              <Mark size={29} />
            </span>
            <span>
              Agent<span className="brand-light">Labs</span>
              <small>YOUR LOCAL LAB</small>
            </span>
          </button>
          <button
            className="new-chat"
            onClick={() => {
              setConversationId(null);
              setDraftSequence((n) => n + 1);
              setView("talk");
              setInput("");
            }}
          >
            <Plus size={17} /> Cuộc trò chuyện mới
          </button>
          <nav>
            {NAV.map((n) => (
              <button
                key={n.id}
                className={"nav-item " + (view === n.id ? "selected" : "")}
                onClick={() => setView(n.id)}
              >
                <n.icon size={17} />
                {n.label}
                {n.id === "library" && !!run?.sources?.length && (
                  <small>{run.sources.length}</small>
                )}
              </button>
            ))}
          </nav>
          <div className="sidebar-label">
            GẦN ĐÂY <span>{conversations.length + runs.length}</span>
          </div>
          <div className="history">
            {conversations.map((c) => (
              <button
                key={c.id}
                className={
                  "history-item " +
                  (view === "talk" && conversationId === c.id ? "current" : "")
                }
                onClick={() => {
                  setConversationId(c.id);
                  setView("talk");
                }}
              >
                <MessageSquare size={12} />
                <span>{c.topic}</span>
                {c.status === "responding" && (
                  <LoaderCircle size={11} className="spin" />
                )}
              </button>
            ))}
            {!!runs.length && (
              <div className="history-section-label">RESEARCH LAB</div>
            )}
            {runs.length
              ? runs.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => {
                      setSelected(r.id);
                      setView("chat");
                    }}
                    className={
                      "history-item " +
                      (view === "chat" && selected === r.id ? "current" : "")
                    }
                  >
                    <span className={"dot " + r.status} />
                    <span>{r.topic}</span>
                  </button>
                ))
              : !conversations.length && (
                  <p className="history-empty">
                    Những câu hỏi lớn
                    <br />
                    bắt đầu từ đây.
                  </p>
                )}
          </div>
          <button className="budget-mini" onClick={() => setView("costs")}>
            <Wallet size={17} />
            <span>
              Ngân sách tháng
              <strong>
                {money(usage?.spent_and_reserved)}{" "}
                <em>/ ${usage?.budget || 15}</em>
              </strong>
              <span className="meter">
                <i
                  style={{
                    width:
                      Math.min(
                        100,
                        ((usage?.spent_and_reserved || 0) /
                          (usage?.budget || 1)) *
                          100,
                      ) + "%",
                  }}
                />
              </span>
            </span>
            <ChevronRight size={15} />
          </button>
          <button
            className={
              "sidebar-bottom " + (view === "settings" ? "selected" : "")
            }
            onClick={() => setView("settings")}
          >
            <span className="profile">ME</span>
            <span>
              Personal workspace
              <small>
                <span className="online-dot" /> Local · chỉ trên máy bạn
              </small>
            </span>
            <SlidersHorizontal size={16} />
          </button>
        </aside>
      )}
      <div className="workspace">
        <header className="topbar">
          <div className="top-left">
            <button
              className="icon-btn"
              aria-label="Ẩn hiện sidebar"
              onClick={() => setSidebar(!sidebar)}
            >
              {sidebar ? (
                <PanelLeftClose size={18} />
              ) : (
                <PanelLeftOpen size={18} />
              )}
            </button>
            <span className="breadcrumb">
              Workspace <ChevronRight size={12} />{" "}
              <strong>
                {view === "costs"
                  ? "Chi phí & ngân sách"
                  : view === "settings"
                    ? "Cấu hình harness"
                    : NAV.find((n) => n.id === view)?.label}
              </strong>
            </span>
          </div>
          <div className="top-right">
            <Badge>
              <span className="online-dot" /> LOCAL
            </Badge>
            <button
              className="icon-btn"
              title="Cấu hình"
              aria-label="Cấu hình"
              onClick={() => setView("settings")}
            >
              <SlidersHorizontal size={17} />
            </button>
          </div>
        </header>
        {error && (
          <div className="error-banner" role="alert">
            <Info size={17} />
            <span>{error}</span>
            <button
              className="icon-btn"
              aria-label="Đóng thông báo"
              onClick={() => setError("")}
            >
              <X size={16} />
            </button>
          </div>
        )}
        <div className="body-grid">
          <main
            className={
              "main-content " +
              (view === "talk"
                ? "talk-content"
                : run && view === "chat"
                  ? "with-run"
                  : "")
            }
          >
            {view === "talk" && (
              <Conversation
                key={conversationId || `new-${draftSequence}`}
                api={api}
                Md={Md}
                modes={MODES}
                config={config}
                id={conversationId}
                onSelect={setConversationId}
                onChanged={() => refresh()}
                onOpenLab={(id) => {
                  setSelected(id);
                  setView("chat");
                }}
              />
            )}
            {view === "chat" && (
              <>
                {!run ? (
                  <div className="welcome">
                    <div className="welcome-eyebrow">
                      <span className="fine-line" /> FROM CURIOSITY TO EVIDENCE{" "}
                      <span className="fine-line" />
                    </div>
                    <div className="hero-mark">
                      <Mark size={66} />
                    </div>
                    <h1>
                      Một ý tưởng.
                      <br />
                      <span>Cả phòng lab cùng bạn.</span>
                    </h1>
                    <p>
                      Đọc tài liệu, thiết kế thực nghiệm, kiểm chứng và viết
                      paper.
                      <br />
                      Một không gian để đi từ câu hỏi đến kết quả có thể tái
                      lập.
                    </p>
                    <div className="welcome-pills">
                      <span>
                        <GitBranch size={13} /> 10 vai trò · 4 reviewer
                      </span>
                      <span>
                        <ShieldCheck size={13} /> Bạn giữ quyền quyết định
                      </span>
                      <button onClick={() => setView("costs")}>
                        <Wallet size={13} /> $10–20 / tháng
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="conversation">
                    <div className="button-row">
                      <button
                        className="text-link"
                        onClick={() =>
                          action(async () => {
                            let id = run.conversation_id;
                            if (!id) {
                              const c = await api("/conversations", {
                                method: "POST",
                                body: JSON.stringify({
                                  mode: run.mode,
                                  budget: run.budget,
                                  research_id: run.id,
                                }),
                              });
                              id = c.id;
                            }
                            setConversationId(id);
                            setView("talk");
                          })
                        }
                      >
                        <MessageSquare size={14} />
                        {run.conversation_id
                          ? "Quay lại hội thoại"
                          : "Chat về nghiên cứu này"}
                      </button>
                      <button
                        className="text-link"
                        onClick={() => {
                          setSelected(null);
                          setInput("");
                        }}
                      >
                        Nhiệm vụ lab mới <Plus size={13} />
                      </button>
                    </div>
                    <div className="run-heading">
                      <div>
                        <div className="eyebrow">
                          RESEARCH SESSION · {run.id.slice(0, 8)}
                        </div>
                        <h2>{run.topic}</h2>
                      </div>
                      <Badge
                        tone={
                          active
                            ? "green"
                            : run.status === "error"
                              ? "red"
                              : "amber"
                        }
                      >
                        {active && <LoaderCircle size={12} className="spin" />}
                        {STATUS[run.status]}
                      </Badge>
                    </div>
                    <div className="session-meta">
                      <span>{MODES[run.mode]}</span>
                      <span>
                        {stagesDone}/{config?.roles.length || 10} vai trò hoàn
                        tất
                      </span>
                      <span>
                        {money(run.spend)} / ${run.budget}
                      </span>
                    </div>
                    {run.mode === "demo" && (
                      <div className="notice">
                        <Info size={15} />
                        Demo dùng nội dung theo kịch bản để thử luồng. Tìm kiếm
                        ở tab Tài liệu là thật; chưa có kết quả nghiên cứu.
                      </div>
                    )}
                    {config?.roles.map((role) => {
                      const text = run.outputs?.[role.id];
                      const running =
                        active &&
                        (run.stage === role.id ||
                          run.active_roles?.includes(role.id));
                      if (!text && !running) return null;
                      return (
                        <article className="agent-message" key={role.id}>
                          <div
                            className="avatar"
                            style={{
                              background: role.color + "18",
                              color: role.color,
                            }}
                          >
                            {role.initials}
                          </div>
                          <div className="message-body">
                            <div className="message-author">
                              <strong>{role.name}</strong>
                              <span>{role.department}</span>
                              {running && (
                                <LoaderCircle className="spin" size={13} />
                              )}
                            </div>
                            {text ? (
                              <Md>{text}</Md>
                            ) : (
                              <div className="working">
                                <i />
                                <i />
                                <i />
                                <span>
                                  Đang làm việc · xem tool log bên phải
                                </span>
                              </div>
                            )}
                          </div>
                        </article>
                      );
                    })}
                    {run.gate?.kind === "experiment" && (
                      <div className="approval-card">
                        <ShieldCheck size={24} />
                        <div>
                          <h3>Protocol và mã đã sẵn sàng để bạn xem</h3>
                          <p>
                            Đọc mã trước khi chạy. Docker: 2 CPU · 1 GB RAM ·
                            tối đa 120 giây · không internet.
                          </p>
                          <div className="button-row">
                            <button
                              className="btn primary"
                              onClick={() => {
                                setView("experiments");
                              }}
                            >
                              <FlaskConical size={15} />
                              Xem & duyệt thực nghiệm
                            </button>
                            <button
                              className="btn"
                              disabled={busy}
                              onClick={() => decide("skip")}
                            >
                              Bỏ qua, tiếp tục bản nháp
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                    {run.gate?.kind === "rework" && (
                      <div className="approval-card">
                        <ShieldCheck size={23} />
                        <div>
                          <h3>Review Chair đề nghị quay lại nghiên cứu</h3>
                          <p>
                            Đã lưu ba sealed reviews và quyết định của Chair.
                            Cần bạn duyệt trước vòng bổ sung.
                          </p>
                          <button
                            className="btn primary"
                            onClick={() => setView("reviews")}
                          >
                            Xem hội đồng & quyết định
                          </button>
                        </div>
                      </div>
                    )}
                    {run.gate?.kind === "draft" && (
                      <div className="approval-card">
                        <FileText size={23} />
                        <div>
                          <h3>Bản nháp cần tác giả đánh giá</h3>
                          <p>
                            Đọc manuscript, nguồn và phản biện trước khi sử
                            dụng.
                          </p>
                          <div className="button-row">
                            <button
                              className="btn"
                              onClick={() => setView("paper")}
                            >
                              Xem bản thảo
                            </button>
                            <button
                              className="btn primary"
                              disabled={busy}
                              onClick={() => decide("acknowledge")}
                            >
                              Xác nhận đã nhận bản nháp
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                    {run.error && (
                      <div className="notice warning">{run.error}</div>
                    )}
                    <div className="session-actions">
                      {active && (
                        <button
                          className="btn"
                          onClick={() =>
                            action(() =>
                              api(`/runs/${selected}/pause`, {
                                method: "POST",
                              }),
                            )
                          }
                        >
                          <Pause size={14} />
                          Tạm dừng
                        </button>
                      )}
                      {["draft", "error", "interrupted"].includes(
                        run.status,
                      ) && (
                        <button
                          className="btn"
                          disabled={busy}
                          onClick={() =>
                            action(() =>
                              api(`/runs/${selected}/resume`, {
                                method: "POST",
                              }),
                            )
                          }
                        >
                          <Play size={14} />
                          Tiếp tục checkpoint
                        </button>
                      )}
                      {!active && (
                        <a
                          className="btn"
                          href={`/api/runs/${selected}/export`}
                        >
                          <Download size={14} />
                          Export research pack
                        </a>
                      )}
                    </div>
                  </div>
                )}
                <div className={"composer-area " + (!run ? "centered" : "")}>
                  <form className="composer" onSubmit={start}>
                    <textarea
                      aria-label="Câu hỏi nghiên cứu"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          start(e);
                        }
                      }}
                      placeholder={
                        run
                          ? "Đặt câu hỏi tiếp theo hoặc mở hướng nghiên cứu mới…"
                          : "Bạn đang muốn khám phá điều gì?"
                      }
                      rows={2}
                      maxLength={8000}
                    />
                    <div className="upload-line">
                      <label className="attach-label">
                        <Plus size={12} />
                        <span>Thêm PDF / dataset</span>
                        <input
                          type="file"
                          accept=".pdf,.txt,.md,.csv,.json"
                          multiple
                          onChange={(e) => {
                            setAttachments(
                              Array.from(e.target.files).slice(0, 5),
                            );
                            e.target.value = "";
                          }}
                        />
                      </label>
                      {attachments.map((f, i) => (
                        <button
                          type="button"
                          key={i}
                          onClick={() =>
                            setAttachments(
                              attachments.filter((_, j) => j !== i),
                            )
                          }
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
                          className={"icon-btn " + (showNotes ? "active" : "")}
                          title="Thêm ràng buộc nghiên cứu"
                          aria-label="Thêm ràng buộc nghiên cứu"
                          onClick={() => setShowNotes(!showNotes)}
                        >
                          <Plus size={19} />
                        </button>
                        <span className="mode-select">
                          <select
                            aria-label="Chế độ model"
                            value={mode}
                            onChange={(e) => {
                              setMode(e.target.value);
                              if (e.target.value === "openclaw") setBudget(2);
                            }}
                          >
                            {Object.entries(MODES).map(([id, label]) => (
                              <option value={id} key={id}>
                                {label}
                              </option>
                            ))}
                          </select>
                          <ChevronDown size={13} />
                        </span>
                      </div>
                      <button
                        type="submit"
                        className="send-btn"
                        title="Bắt đầu research workflow"
                        aria-label="Bắt đầu nghiên cứu"
                        disabled={busy || active || input.trim().length < 5}
                      >
                        {busy ? (
                          <LoaderCircle size={19} className="spin" />
                        ) : (
                          <ArrowUp size={20} />
                        )}
                      </button>
                    </div>
                    {showNotes && (
                      <div className="composer-extra">
                        <label>
                          Số vòng sửa tối đa sau review
                          <select
                            value={maxRevisions}
                            onChange={(e) =>
                              setMaxRevisions(Number(e.target.value))
                            }
                          >
                            <option value={0}>0 · chỉ review, tiết kiệm</option>
                            <option value={1}>1 · cho phép một vòng sửa</option>
                          </select>
                        </label>
                        <label>
                          Ràng buộc, dataset, GPU, tiêu chí thành công
                          <textarea
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            placeholder="Ví dụ: CPU-only, dataset public, 3 seeds, ưu tiên baseline đơn giản…"
                            rows={2}
                          />
                        </label>
                        <label>
                          Giới hạn API mỗi lượt (USD)
                          <input
                            type="number"
                            value={budget}
                            min="0.05"
                            max="20"
                            step="0.05"
                            onChange={(e) => setBudget(e.target.value)}
                          />
                        </label>
                        {selected && (
                          <label className="checkbox-label">
                            <input
                              type="checkbox"
                              checked={followup}
                              onChange={(e) => setFollowup(e.target.checked)}
                            />{" "}
                            Kèm bản nháp và nguồn của lượt hiện tại
                          </label>
                        )}
                      </div>
                    )}
                  </form>
                  <p className="composer-foot">
                    <ShieldCheck size={12} />
                    {mode === "demo"
                      ? "Demo không cần API key. Chọn Lean hoặc Hybrid trong cấu hình để nghiên cứu bằng model."
                      : "Cloud mode gửi prompt/snippets tới provider đã chọn. Mỗi lần gửi mở workflow mới, không tự fallback trả phí."}
                  </p>
                  {!run && (
                    <div className="suggestions">
                      {[
                        {
                          icon: BookOpen,
                          label: "Khảo sát một hướng nghiên cứu",
                          text: "Khảo sát các phương pháp giảm hallucination trong retrieval augmented generation, xác định baseline và một research gap có thể kiểm chứng.",
                        },
                        {
                          icon: FlaskConical,
                          label: "Thiết kế một thực nghiệm",
                          text: "Thiết kế thực nghiệm so sánh LoRA và full fine-tuning trên dữ liệu nhỏ, kiểm soát compute budget và data leakage.",
                        },
                        {
                          icon: FileText,
                          label: "Phát triển ý tưởng thành paper",
                          text: "Giúp tôi phát triển ý tưởng adaptive retrieval cho RAG thành giả thuyết, protocol ablation và cấu trúc paper.",
                        },
                      ].map((s) => (
                        <button key={s.label} onClick={() => setInput(s.text)}>
                          <s.icon size={18} />
                          <span>{s.label}</span>
                          <ArrowUpRight size={14} />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {!run && (
                  <div className="bottom-note">
                    <span>BUILT FOR THOUGHTFUL RESEARCH</span>
                    <p>
                      LangGraph checkpoints <i /> OpenClaw adapter <i /> Local
                      artifacts <i /> Human review
                    </p>
                  </div>
                )}
              </>
            )}
            {view === "library" && (
              <section className="page">
                <div className="eyebrow">LITERATURE & EVIDENCE</div>
                <h1>
                  Tài liệu có nguồn.
                  <br />
                  <span>Lập luận có căn cứ.</span>
                </h1>
                <p className="page-intro">
                  Tìm metadata Crossref hoặc abstract arXiv. Mỗi nguồn ghi rõ
                  mức độ đã đọc; full text cần kiểm tra riêng.
                </p>
                <form className="search-bar" onSubmit={search}>
                  <Search size={18} />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Tên paper, tác giả hoặc research topic…"
                    aria-label="Tìm tài liệu"
                    required
                    minLength={2}
                  />
                  <select
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                    aria-label="Nguồn tìm kiếm"
                  >
                    <option value="crossref">Crossref</option>
                    <option value="arxiv">arXiv</option>
                  </select>
                  <button
                    className="btn primary"
                    disabled={searching || active}
                  >
                    {searching ? (
                      <LoaderCircle size={16} className="spin" />
                    ) : (
                      "Tìm kiếm"
                    )}
                  </button>
                </form>
                <div className="document-panel">
                  <div className="section-line">
                    <h3>
                      Tài liệu local đã nhập ·{" "}
                      {(run?.documents?.length || 0) +
                        (run?.datasets?.length || 0)}
                    </h3>
                    {selected && (
                      <label className="attach-label">
                        <Plus size={12} />
                        Nhập PDF / dataset
                        <input
                          type="file"
                          accept=".pdf,.txt,.md,.csv,.json"
                          disabled={active || busy}
                          onChange={async (e) => {
                            const file = e.target.files[0];
                            e.target.value = "";
                            if (file)
                              await action(() => upload(selected, file));
                          }}
                        />
                      </label>
                    )}
                  </div>
                  {[...(run?.documents || []), ...(run?.datasets || [])].map(
                    (d) => (
                      <button
                        className="document-card"
                        key={d.id}
                        onClick={() => artifact(d.artifact)}
                      >
                        <FileText size={16} />
                        <span>
                          <strong>{d.title}</strong>
                          <small>
                            {d.chunks
                              ? d.chunks + " chunks"
                              : "Dataset · /inputs read-only"}{" "}
                            · {d.id} · {d.evidence}
                          </small>
                        </span>
                        <ArrowUpRight size={13} />
                      </button>
                    ),
                  )}
                  <p>
                    Chunk giữ số trang và SHA256. Model có thể gọi
                    search_documents để đọc đoạn liên quan. PDF scan cần OCR
                    trước; tối đa 50 trang/file. CSV/JSON được gắn read-only vào
                    sandbox; mỗi file tối đa 10 MB.
                  </p>
                </div>
                <div className="section-line">
                  <span>
                    {currentSources.length} nguồn{" "}
                    {papers.length
                      ? searchSaved
                        ? "· đã lưu vào nghiên cứu"
                        : "· xem trước, chưa gắn nghiên cứu"
                      : "trong nghiên cứu"}
                  </span>
                  {selected && (
                    <a
                      href={`/api/runs/${selected}/artifacts/references.bib`}
                      className="text-link"
                    >
                      Export BibTeX <Download size={13} />
                    </a>
                  )}
                </div>
                {currentSources.length ? (
                  <div className="paper-list">
                    {currentSources.map((p, i) => (
                      <article className="paper-card" key={p.id}>
                        <div className="paper-number">
                          {String(i + 1).padStart(2, "0")}
                        </div>
                        <div>
                          <div className="paper-meta">
                            <Badge>{p.source}</Badge>
                            <span>{p.year}</span>
                          </div>
                          <a
                            className="paper-title"
                            href={p.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {p.title}
                            <ArrowUpRight size={15} />
                          </a>
                          <p>{p.authors}</p>
                          {p.abstract && (
                            <details>
                              <summary>Xem abstract</summary>
                              <p>{p.abstract}</p>
                            </details>
                          )}
                          <small className="evidence">
                            <ShieldCheck size={12} />
                            {p.evidence}
                          </small>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <Empty
                    icon={BookOpen}
                    title="Bắt đầu bằng một câu hỏi tốt"
                    text="Tìm nguồn ở trên. Nếu đã chọn nghiên cứu, kết quả sẽ được lưu vào source registry và references.bib."
                  />
                )}
              </section>
            )}
            {view === "agents" && (
              <section className="page">
                <div className="eyebrow">THE RESEARCH TEAM</div>
                <h1>
                  Chuyên môn riêng.
                  <br />
                  <span>Chung một câu hỏi.</span>
                </h1>
                <p className="page-intro">
                  6 agent tác vụ + 3 reviewer độc lập + 1 Review Chair chạy theo
                  checkpoint, truyền bản nháp và evidence qua từng bước. Ba
                  reviewer fan-out sau bản thảo, nộp sealed scorecards rồi Chair
                  tổng hợp. Vòng sửa có giới hạn và checkpoint.
                </p>
                <div className="route-bar">
                  <GitBranch size={16} />
                  <span>Model routing</span>
                  <select
                    aria-label="Xem routing theo chế độ"
                    value={mode}
                    onChange={(e) => {
                      setMode(e.target.value);
                      if (e.target.value === "openclaw") setBudget(2);
                    }}
                  >
                    {Object.entries(MODES).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="agent-grid">
                  {config?.roles.map((r, i) => (
                    <article className="agent-card" key={r.id}>
                      <div className="agent-card-top">
                        <span
                          className="avatar"
                          style={{ color: r.color, background: r.color + "19" }}
                        >
                          {r.initials}
                        </span>
                        <span className="agent-step">
                          {String(i + 1).padStart(2, "0")}
                        </span>
                      </div>
                      <small>{r.department}</small>
                      <h3>{r.name}</h3>
                      <p>{r.brief}</p>
                      <div className="agent-card-bottom">
                        <code>
                          {config.routes?.[mode]?.find((x) => x.role === r.id)
                            ?.model || "OpenClaw routed"}
                        </code>
                        <span>{r.tools.length + 2} tools</span>
                      </div>
                    </article>
                  ))}
                </div>
                <div className="notice">
                  <ShieldCheck size={16} />
                  Code chỉ được stage để xem xét. Tầng harness giữ quyền duyệt
                  và chạy Docker; model không có shell trên host.
                </div>
              </section>
            )}
            {view === "experiments" && (
              <section className="page">
                <div className="eyebrow">REPRODUCIBLE EXPERIMENTS</div>
                <h1>
                  Từ giả thuyết
                  <br />
                  <span>đến phép kiểm chứng.</span>
                </h1>
                <div className="sandbox-status">
                  <Terminal size={18} />
                  <div>
                    <strong>
                      {health?.docker?.ready
                        ? "Docker engine sẵn sàng"
                        : "Docker engine chưa chạy"}
                    </strong>
                    <p>
                      CPU 2 · RAM 1 GB · 120 giây · network off · không truyền
                      API key
                    </p>
                  </div>
                  <button
                    className="icon-btn"
                    aria-label="Kiểm tra Docker"
                    onClick={() => api("/health").then(setHealth)}
                  >
                    <RefreshCw size={16} />
                  </button>
                </div>
                {run?.experiment ? (
                  <>
                    <div className="section-line">
                      <span>
                        experiment.py{" "}
                        <Badge>
                          {run.mode === "demo"
                            ? "SYNTHETIC SMOKE TEST"
                            : "UNREVIEWED CODE"}
                        </Badge>
                      </span>
                      <button
                        className="text-link"
                        onClick={() => artifact("methods.md")}
                      >
                        Xem protocol <ArrowUpRight size={13} />
                      </button>
                    </div>
                    <pre className="code-block">{run.experiment.code}</pre>
                    <div className="hash-line">
                      SHA256 <code>{run.experiment.sha256}</code>
                    </div>
                    {run.gate?.kind === "experiment" && (
                      <div className="approval-card">
                        <ShieldCheck size={23} />
                        <div>
                          <h3>Chạy đúng mã đã xem ở trên?</h3>
                          <p>
                            Chỉ sandbox Docker được phép thực thi. Cần build
                            image trước bằng lệnh trong README.
                          </p>
                          <button
                            className="text-link"
                            onClick={() =>
                              action(() =>
                                api(`/runs/${selected}/refresh-experiment`, {
                                  method: "POST",
                                }),
                              )
                            }
                          >
                            <RefreshCw size={12} />
                            Đọc lại hash sau khi sửa experiment.py local
                          </button>
                          <div className="button-row">
                            <button
                              className="btn primary"
                              disabled={busy || !health?.docker?.ready}
                              onClick={() => decide("run")}
                            >
                              <Play size={14} />
                              Duyệt & chạy Docker
                            </button>
                            <button
                              className="btn"
                              disabled={busy}
                              onClick={() => decide("skip")}
                            >
                              Bỏ qua thực nghiệm
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                    {run.execution?.status && (
                      <div className="notice">
                        Execution: {run.execution.status}.{" "}
                        {run.execution.reason || run.execution.scope}
                      </div>
                    )}
                    <ArtifactList
                      run={run}
                      selected={selected}
                      artifact={artifact}
                    />
                  </>
                ) : (
                  <Empty
                    icon={FlaskConical}
                    title="Một thực nghiệm, đầy đủ dấu vết"
                    text="Bắt đầu workflow ở Không gian nghiên cứu. Research Engineer sẽ stage mã để bạn kiểm tra trước khi chạy."
                  />
                )}
              </section>
            )}
            {view === "reviews" && (
              <section className="page">
                <div className="eyebrow">INDEPENDENT PEER REVIEW</div>
                <h1>
                  Nhiều góc nhìn.
                  <br />
                  <span>Cùng một bộ bằng chứng.</span>
                </h1>
                <p className="page-intro">
                  R1 kiểm tra novelty & nguồn, R2 kiểm tra phương pháp & thống
                  kê, R3 kiểm tra khả năng tái lập. Các báo cáo được cách ly
                  trước khi Chair tổng hợp; điểm số không thay thế thẩm định
                  khoa học.
                </p>
                {run?.board && (
                  <div className="board-card">
                    <div className="page-title-row">
                      <h3>Review Chair · {run.board.verdict}</h3>
                      <Badge tone="amber">
                        VÒNG {run.revision_count || 0} /{" "}
                        {run.max_revisions ?? 1}
                      </Badge>
                    </div>
                    <p>{run.board.reason}</p>
                    <strong>Hướng tiếp theo: {run.board.action}</strong>
                    <ul>
                      {run.board.recommended_fixes?.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                    <button
                      className="text-link"
                      onClick={() => artifact("board-decision.json")}
                    >
                      Mở quyết định có cấu trúc <ArrowUpRight size={12} />
                    </button>
                  </div>
                )}
                {run?.gate?.kind === "rework" && (
                  <div className="approval-card">
                    <ShieldCheck size={23} />
                    <div>
                      <h3>Hội đồng yêu cầu thêm nghiên cứu</h3>
                      <p>
                        Chọn duyệt để quay lại{" "}
                        {run.gate.action === "more_literature"
                          ? "tổng quan tài liệu"
                          : "thiết kế thực nghiệm"}
                        . Lần chạy code mới vẫn cần duyệt riêng.
                      </p>
                      <div className="button-row">
                        <button
                          className="btn primary"
                          disabled={busy}
                          onClick={() => decide("rework")}
                        >
                          Duyệt một vòng làm lại
                        </button>
                        <button
                          className="btn"
                          disabled={busy}
                          onClick={() => decide("finish")}
                        >
                          Giữ bản nháp hiện tại
                        </button>
                      </div>
                    </div>
                  </div>
                )}
                <div className="review-grid">
                  {config?.roles
                    .filter((r) => r.id.startsWith("review"))
                    .map((r) => {
                      const report = run?.reviews?.[r.id];
                      return (
                        <article className="review-card" key={r.id}>
                          <div className="page-title-row">
                            <span
                              className="avatar"
                              style={{
                                color: r.color,
                                background: r.color + "18",
                              }}
                            >
                              {r.initials}
                            </span>
                            <Badge
                              tone={
                                report?.verdict === "ready_for_human"
                                  ? "green"
                                  : "amber"
                              }
                            >
                              {report?.verdict || "Chưa nộp"}
                            </Badge>
                          </div>
                          <h3>{r.name}</h3>
                          {report ? (
                            <>
                              <div className="review-score">
                                <strong>
                                  {report.score}
                                  <small>/5</small>
                                </strong>
                                <span>
                                  confidence {report.confidence}
                                  <br />
                                  round {report.round}
                                </span>
                              </div>
                              <p>{report.rationale}</p>
                              <h4>Vấn đề chặn</h4>
                              <ul>
                                {report.blocking_issues.map((x, i) => (
                                  <li key={i}>{x}</li>
                                ))}
                              </ul>
                              <h4>Đề xuất sửa</h4>
                              <ul>
                                {report.recommended_fixes.map((x, i) => (
                                  <li key={i}>{x}</li>
                                ))}
                              </ul>
                              <div className="review-refs">
                                {report.evidence_refs.map((x) => (
                                  <code key={x}>{x}</code>
                                ))}
                              </div>
                              <button
                                className="text-link"
                                onClick={() => artifact(r.id + ".json")}
                              >
                                Scorecard JSON <ArrowUpRight size={12} />
                              </button>
                            </>
                          ) : (
                            <p>{r.brief}</p>
                          )}
                        </article>
                      );
                    })}
                </div>
                {!run && (
                  <div className="notice">
                    Chọn một nghiên cứu để xem hội đồng. Báo cáo mỗi vòng được
                    giữ ở artifact riêng.
                  </div>
                )}
              </section>
            )}
            {view === "paper" && (
              <section className="page">
                <div className="page-title-row">
                  <div>
                    <div className="eyebrow">MANUSCRIPT WORKSPACE</div>
                    <h1>Bản thảo của bạn.</h1>
                  </div>
                  {run?.outputs?.writing && (
                    <a
                      className="btn"
                      href={`/api/runs/${selected}/artifacts/manuscript.md`}
                    >
                      <Download size={15} />
                      Markdown
                    </a>
                  )}
                </div>
                {run?.outputs?.writing ? (
                  <>
                    <div className="notice">
                      <FileText size={16} />
                      Bản nháp chưa được xác minh; export không đồng nghĩa đã
                      review hoặc sẵn sàng nộp.
                    </div>
                    <div className="manuscript">
                      <Md>{run.outputs.writing}</Md>
                    </div>
                    {run.quality && (
                      <div className="quality-panel">
                        <h3>Evidence audit · cần tác giả kiểm tra</h3>
                        {run.quality.checks.map((c) => (
                          <div key={c.name}>
                            <span>{c.name}</span>
                            <Badge
                              tone={c.status === "pass" ? "green" : "amber"}
                            >
                              {c.status}
                            </Badge>
                          </div>
                        ))}
                        <button
                          className="text-link"
                          onClick={() => artifact("quality-gates.json")}
                        >
                          Xem chi tiết kiểm tra <ArrowUpRight size={12} />
                        </button>
                      </div>
                    )}
                    {run.outputs.review && (
                      <div className="review-box">
                        <h3>
                          <ShieldCheck size={18} /> Critical review
                        </h3>
                        <Md>{run.outputs.review}</Md>
                      </div>
                    )}
                    {run.gate?.kind === "draft" && (
                      <button
                        className="btn primary"
                        disabled={busy}
                        onClick={() => decide("acknowledge")}
                      >
                        Xác nhận đã nhận bản nháp
                      </button>
                    )}
                  </>
                ) : (
                  <Empty
                    icon={FileText}
                    title="Viết từ bằng chứng"
                    text="Scientific Writer sẽ tổng hợp bản nháp sau bước thực nghiệm và phân tích. Chưa có số liệu thì Results được đánh dấu TODO."
                  />
                )}
              </section>
            )}
            {view === "costs" && (
              <section className="page">
                <div className="eyebrow">A SMALL BUDGET, USED WELL</div>
                <h1>
                  Nghiên cứu sâu.
                  <br />
                  <span>Chi tiêu có giới hạn.</span>
                </h1>
                <p className="page-intro">
                  Đề xuất của bạn: $10–20/tháng cho API, thực nghiệm CPU local.
                  Dành model mạnh cho Methods và Review; còn lại dùng model rẻ
                  hoặc quota free.
                </p>
                <div className="cost-summary">
                  <div>
                    <small>THÁNG {usage?.month}</small>
                    <strong>{money(usage?.spent_and_reserved)}</strong>
                    <span>ước tính + dự phòng</span>
                  </div>
                  <div>
                    <small>NGÂN SÁCH THÁNG</small>
                    <strong>${usage?.budget || 15}</strong>
                    <span>chặn trước API call tiếp theo</span>
                  </div>
                  <div>
                    <small>GPU CLOUD</small>
                    <strong>$0</strong>
                    <span>không có GPU cloud được kết nối</span>
                  </div>
                </div>
                <div className="estimator">
                  <div>
                    <h3>Ước lượng kế hoạch tháng</h3>
                    <p>
                      Giả định mỗi workflow: 300k input + 45k output ở model rẻ;
                      40k input + 8k output ở Sol. Không cache, giá Standard.
                    </p>
                    <label>
                      {calls} workflows / tháng
                      <input
                        type="range"
                        min="5"
                        max="80"
                        step="5"
                        value={calls}
                        onChange={(e) => setCalls(Number(e.target.value))}
                      />
                    </label>
                  </div>
                  <div className="estimate-result">
                    <small>LEAN / HYBRID</small>
                    <strong>
                      ${(calls * 0.2125).toFixed(2)}{" "}
                      <em>/ ${(calls * 0.16).toFixed(2)}</em>
                    </strong>
                    <span>ước lượng API, chưa gồm thuế/phí nạp tiền</span>
                  </div>
                </div>
                <div className="notice">
                  <Info size={16} />
                  Một đề tài có thể cần nhiều workflow. Free quota phụ thuộc tài
                  khoản và model; không giả định unlimited hay tín dụng miễn phí
                  vĩnh viễn. Rate limit sẽ dừng lượt, không tự gọi model trả
                  phí.
                </div>
                <div className="section-line">
                  <h3>Giá tham chiếu · {config?.price_date}</h3>
                  <span>USD / 1M tokens</span>
                </div>
                <table className="price-table">
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Input</th>
                      <th>Output</th>
                      <th>Sử dụng</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(config?.models || {}).map(([id, r]) => (
                      <tr key={id}>
                        <td>{id}</td>
                        <td>${r.input}</td>
                        <td>${r.output}</td>
                        <td>
                          {id === "gpt-6-luna"
                            ? "Phần lớn tác vụ"
                            : id === "gpt-6.1-sol"
                              ? "Methods + Review"
                              : id.includes("astra")
                                ? "Đề xuất mở rộng · chưa route"
                                : "Chế độ Claude tùy chọn"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="source-links">
                  Nguồn giá:{" "}
                  <a
                    href="https://developers.openai.com/api/docs/pricing"
                    target="_blank"
                    rel="noreferrer"
                  >
                    OpenAI
                  </a>{" "}
                  ·{" "}
                  <a
                    href="https://platform.claude.com/docs/en/about-claude/pricing"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Anthropic
                  </a>{" "}
                  ·{" "}
                  <a
                    href="https://openrouter.ai/pricing"
                    target="_blank"
                    rel="noreferrer"
                  >
                    OpenRouter quota
                  </a>
                </p>
                <div className="section-line">
                  <h3>Usage ledger</h3>
                  <span>Ước tính ứng dụng, không phải hóa đơn</span>
                </div>
                {usage?.ledger?.length ? (
                  <div className="ledger">
                    {usage.ledger.slice(0, 30).map((u) => (
                      <div key={u.id}>
                        <span>
                          {u.model}
                          <small>
                            {u.input_tokens} in · {u.output_tokens} out ·{" "}
                            {u.status}
                          </small>
                        </span>
                        <code>{money(u.cost + u.reserved)}</code>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-small">
                    Chưa có API call. Demo không phát sinh token.
                  </div>
                )}
              </section>
            )}
            {view === "settings" && (
              <section className="page">
                <div className="eyebrow">LOCAL HARNESS</div>
                <h1>
                  Phòng lab của bạn.
                  <br />
                  <span>Quy tắc của bạn.</span>
                </h1>
                <div className="settings-card">
                  <h3>Giới hạn ngân sách</h3>
                  <p>
                    Giới hạn ước tính trong ứng dụng. Usage ngoài Research
                    Studio không được tính; vẫn nên đặt spending limit ở nhà
                    cung cấp.
                  </p>
                  <div className="button-row">
                    <label className="budget-input">
                      USD / tháng
                      <input
                        aria-label="Ngân sách tháng"
                        type="number"
                        value={monthly}
                        min="0"
                        max="1000"
                        onChange={(e) => setMonthly(e.target.value)}
                      />
                    </label>
                    <button
                      className="btn primary"
                      onClick={() =>
                        action(async () => {
                          await api("/settings", {
                            method: "PUT",
                            body: JSON.stringify({
                              monthly_budget: Number(monthly),
                            }),
                          });
                          setConfig(await api("/config"));
                        })
                      }
                    >
                      Lưu giới hạn
                    </button>
                  </div>
                </div>
                <div className="settings-card">
                  <h3>Model connections</h3>
                  <p>
                    Thêm key trong file <code>.env</code> rồi khởi động lại
                    backend. Key không lưu trong browser hoặc research pack.
                  </p>
                  {[
                    [
                      "openai",
                      "OpenAI",
                      "OPENAI_API_KEY · Lean / model mạnh trong Hybrid",
                    ],
                    [
                      "gateway",
                      "OpenRouter free",
                      "GATEWAY_API_KEY + GATEWAY_MODEL=:free",
                    ],
                    [
                      "anthropic",
                      "Anthropic",
                      "ANTHROPIC_API_KEY · tùy chọn, tốn phí cao hơn",
                    ],
                    [
                      "local",
                      "Ollama / local",
                      "LOCAL_LLM_URL + LOCAL_MODEL · cần tự chạy server",
                    ],
                  ].map(([k, title, desc]) => (
                    <div className="connection" key={k}>
                      <span className="connection-icon">
                        <Terminal size={18} />
                      </span>
                      <span>
                        <strong>{title}</strong>
                        <small>{desc}</small>
                      </span>
                      <Badge
                        tone={
                          config?.configured[k] && k !== "local" ? "green" : ""
                        }
                      >
                        {k === "local"
                          ? "Chưa probe"
                          : config?.configured[k]
                            ? "Có key · chưa test"
                            : "Chưa cấu hình"}
                      </Badge>
                    </div>
                  ))}
                </div>
                <div className="settings-card">
                  <div className="page-title-row">
                    <h3>OpenClaw local runtime</h3>
                    <Badge tone="amber">OPTIONAL BRIDGE</Badge>
                  </div>
                  <p>
                    OpenClaw được clone riêng, pin v2026.10.7. Harness gọi
                    OpenResponses trên loopback, truyền function tools theo từng
                    vai trò. Cần setup runtime và model key trước khi chọn chế
                    độ OpenClaw.
                  </p>
                  <code>
                    powershell -ExecutionPolicy Bypass -File
                    .\scripts\openclaw.ps1 -Action start
                  </code>
                  <p>
                    Chi phí trong chế độ OpenClaw dùng mức dự phòng cấu hình và
                    usage upstream; cần kiểm tra dashboard nhà cung cấp. Hướng
                    dẫn đầy đủ ở docs/OPENCLAW.md.
                  </p>
                  <a
                    className="text-link"
                    href="https://docs.openclaw.ai/gateway/openresponses-http-api"
                    target="_blank"
                    rel="noreferrer"
                  >
                    OpenClaw OpenResponses contract <ArrowUpRight size={14} />
                  </a>
                </div>
                <div className="section-line">
                  <h3>Nền tảng & trạng thái tích hợp</h3>
                </div>
                <div className="repo-list">
                  {config?.repos.map((r) => (
                    <a
                      key={r.name}
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <div>
                        <strong>
                          {r.name} <ArrowUpRight size={13} />
                        </strong>
                        <p>{r.use}</p>
                      </div>
                      <Badge>{r.license}</Badge>
                    </a>
                  ))}
                </div>
              </section>
            )}
          </main>
          {run && view === "chat" && (
            <aside className="inspector">
              <div className="inspector-head">
                <span>
                  <GitBranch size={15} /> RESEARCH PIPELINE
                </span>
                <Badge>
                  {stagesDone}/{config?.roles.length || 10}
                </Badge>
              </div>
              <p className="inspector-intro">
                Mỗi bước để lại một artifact.
                <br />
                Mọi kết luận cần bằng chứng.
              </p>
              <div className="pipeline">
                {config?.roles.map((r, i) => {
                  const done = !!run.outputs?.[r.id],
                    running =
                      active &&
                      (run.stage === r.id || run.active_roles?.includes(r.id));
                  return (
                    <button
                      key={r.id}
                      className={
                        "pipeline-step " +
                        (done ? "done" : "") +
                        (running ? " running" : "")
                      }
                      onClick={() =>
                        done &&
                        artifact(
                          r.id === "writing" ? "manuscript.md" : r.id + ".md",
                        )
                      }
                    >
                      <span className="pipeline-node">
                        {done ? (
                          <Check size={13} />
                        ) : running ? (
                          <LoaderCircle size={13} className="spin" />
                        ) : (
                          <span>{i + 1}</span>
                        )}
                      </span>
                      <span>
                        <strong>{r.department}</strong>
                        <small>
                          {done
                            ? "Artifact đã lưu"
                            : running
                              ? "Đang làm việc"
                              : "Chờ bước trước"}
                        </small>
                      </span>
                      {done && <ArrowUpRight size={12} />}
                    </button>
                  );
                })}
              </div>
              <div className="inspector-divider" />
              <div className="section-line">
                <strong className="tiny-title">TOOL ACTIVITY</strong>
                <span className="live-dot" />
              </div>
              <div className="activity-list">
                {(run.events || [])
                  .filter((e) =>
                    ["tool", "model", "sandbox", "error", "decision"].includes(
                      e.kind,
                    ),
                  )
                  .slice(-8)
                  .reverse()
                  .map((e) => (
                    <div className="activity" key={e.seq}>
                      <span className="activity-dot" />
                      <div>
                        <strong>
                          {e.kind === "tool"
                            ? e.data.name
                            : e.kind === "model"
                              ? e.data.model
                              : e.kind}
                        </strong>
                        <small>
                          {e.data.detail ||
                            e.data.message ||
                            e.data.action ||
                            `${e.data.provider} · turn ${e.data.turn}`}
                        </small>
                      </div>
                    </div>
                  ))}
                {!(run.events || []).some((e) =>
                  ["tool", "model"].includes(e.kind),
                ) && (
                  <p className="muted-small">
                    {run.mode === "demo"
                      ? "Demo không gọi model/tool tự động."
                      : "Tool calls sẽ hiển thị tại đây."}
                  </p>
                )}
              </div>
              <div className="inspector-divider" />
              <div className="section-line">
                <strong className="tiny-title">ARTIFACTS</strong>
                <FolderOpen size={14} />
              </div>
              <div className="mini-artifacts">
                {(run.artifacts || []).slice(-8).map((a) => (
                  <button key={a.name} onClick={() => artifact(a.name)}>
                    <FileText size={13} />
                    <span>{a.name}</span>
                    <ArrowUpRight size={12} />
                  </button>
                ))}
              </div>
              <div className="inspector-footer">
                <ShieldCheck size={14} />
                <span>
                  Checkpoints tự lưu
                  <br />
                  <strong>SQLite · trên máy bạn</strong>
                </span>
              </div>
            </aside>
          )}
        </div>
      </div>
      {preview && (
        <div className="modal-overlay" onClick={() => setPreview(null)}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={preview.name}
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <span>
                <FileText size={17} />
                {preview.name}
              </span>
              <div className="button-row">
                {!preview.image && (
                  <button
                    className="icon-btn"
                    aria-label="Copy nội dung"
                    onClick={async () => {
                      await navigator.clipboard.writeText(preview.content);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 2000);
                    }}
                  >
                    {copied ? <CheckCheck size={17} /> : <Copy size={17} />}
                  </button>
                )}
                <a
                  className="icon-btn"
                  aria-label="Tải artifact"
                  href={`/api/runs/${selected}/artifacts/${preview.name}`}
                >
                  <Download size={17} />
                </a>
                <button
                  className="icon-btn"
                  aria-label="Đóng artifact"
                  onClick={() => setPreview(null)}
                >
                  <X size={19} />
                </button>
              </div>
            </header>
            <div className="modal-content">
              {preview.image ? (
                <img
                  className="result-image"
                  src={`/api/runs/${selected}/preview/${preview.name}`}
                  alt={preview.name}
                />
              ) : preview.name.endsWith(".md") ? (
                <Md>{preview.content}</Md>
              ) : (
                <pre>{preview.content}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
function Empty({ icon: Icon, title, text }) {
  return (
    <div className="empty-state">
      <Icon size={32} strokeWidth={1.2} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
function ArtifactList({ run, selected, artifact }) {
  return (
    <div className="artifact-grid">
      {run?.artifacts?.map((a) => (
        <button key={a.name} onClick={() => artifact(a.name)}>
          <FileText size={18} />
          <span>
            {a.name}
            <small>{(a.bytes / 1024).toFixed(1)} KB</small>
          </span>
          <ArrowUpRight size={14} />
        </button>
      ))}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
