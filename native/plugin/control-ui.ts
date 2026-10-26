import type {
  ControlUiPlugin,
  ControlUiSurfaceProps,
  ControlUiViewContext,
} from "openclaw/plugin-sdk/control-ui";
import "./control-ui.css";

type ComposerContext = ControlUiViewContext<ControlUiSurfaceProps["composer"]>;
const prefix = /^\s*(?:CHAT:|RESEARCH:|\/chat\b|\/research\b)\s*/i;
const recipes = [
  ["Khảo sát tài liệu", "Hãy khảo sát tài liệu AI/ML cho đề tài: "],
  ["Thiết kế thực nghiệm", "Hãy thiết kế thực nghiệm AI/ML cho đề tài: "],
  ["Viết & phản biện paper", "Hãy viết và phản biện bản nháp từ evidence sau: "],
  ["Nghiên cứu toàn quy trình", "Hãy nghiên cứu toàn quy trình AI/ML cho đề tài: "],
];

const plugin: ControlUiPlugin = {
  id: "agentlabs-research",
  activate(host) {
    const unregister = host.ui.registerReplacement({
      id: "research-composer",
      label: "AgentLabs · Chat & AI/ML",
      surface: "composer",
      mount(container, initial) {
        let current: ComposerContext = initial;
        const root = document.createElement("div");
        root.className = "agentlabs-composer";
        const toolbar = document.createElement("div");
        toolbar.className = "agentlabs-modes";
        toolbar.setAttribute("aria-label", "Chế độ AgentLabs");
        const label = document.createElement("span");
        label.textContent = "AgentLabs";
        label.className = "agentlabs-brand";
        toolbar.append(label);
        const buttons = ["Chat", "Nghiên cứu"].map((text, index) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = text;
          button.onclick = () => {
            if (!current.presented || current.signal.aborted) return;
            const body = current.props.draft.replace(prefix, "");
            current.props.setDraft(`${index ? "RESEARCH" : "CHAT"}: ${body}`);
          };
          toolbar.append(button);
          return button;
        });
        const picker = document.createElement("select");
        picker.setAttribute("aria-label", "Gợi ý tác vụ nghiên cứu");
        picker.add(new Option("Gợi ý tác vụ…", ""));
        recipes.forEach(([name], index) => picker.add(new Option(name, String(index))));
        picker.onchange = () => {
          if (!current.presented || current.signal.aborted || picker.value === "") return;
          const body = current.props.draft.replace(prefix, "");
          // Preserve everything typed; selecting a suggestion never submits a message.
          const recipe = recipes[Number(picker.value)][1];
          current.props.setDraft(`RESEARCH: ${recipe}${body}`);
          picker.value = "";
        };
        toolbar.append(picker);
        const newChat = document.createElement("button");
        newChat.type = "button";
        newChat.textContent = "+ Chat mới";
        newChat.className = "agentlabs-new-chat";
        let creating = false;
        newChat.onclick = async () => {
          if (creating || !current.presented || current.signal.aborted) return;
          const owner = current;
          creating = true;
          newChat.disabled = true;
          try {
            const sessionKey = await owner.host.sessions.create({ agentId: "director" });
            if (sessionKey && !owner.signal.aborted && current.presented)
              owner.host.sessions.open({ sessionKey, agentId: "director" });
          } catch {
            hint.textContent = "Chưa mở được chat mới. Kiểm tra Gateway rồi thử lại.";
          } finally {
            creating = false;
            if (!owner.signal.aborted) newChat.disabled = !current.presented;
          }
        };
        toolbar.append(newChat);
        const builtin = document.createElement("div");
        const hint = document.createElement("div");
        hint.className = "agentlabs-hint";
        root.append(toolbar, builtin, hint);
        container.append(root);
        const disposeDefault = initial.mountDefault(builtin);
        function update(context: ComposerContext) {
          current = context;
          const research = /^(RESEARCH:|\/research\b)/i.test(context.props.draft.trimStart());
          const director = context.props.agentId === "director";
          toolbar.hidden = !director;
          hint.hidden = !director;
          buttons.forEach((button, index) => {
            button.setAttribute("aria-pressed", String(index === (research ? 1 : 0)));
            button.disabled = !context.presented || context.props.sending;
          });
          picker.hidden = !research;
          picker.disabled = !context.presented || context.props.sending;
          newChat.disabled = creating || !context.presented || !context.host.connection.canWrite;
          hint.textContent = research
            ? "Chọn tác vụ để mở luồng phù hợp. Code thực nghiệm cần bạn duyệt; bản nháp qua 3 reviewer và Chair."
            : "Chat bình thường. Khi muốn giao việc nghiên cứu, chọn Nghiên cứu hoặc nêu yêu cầu cụ thể.";
        }
        update(initial);
        return {
          update,
          dispose() { disposeDefault(); root.remove(); },
        };
      },
    });
    const unregisterWelcome = host.ui.registerReplacement({
      id: "research-transcript",
      label: "AgentLabs · AI/ML welcome",
      surface: "transcript",
      mount(container, initial) {
        let disposeDefault: (() => void) | undefined;
        let welcome: HTMLElement | undefined;
        function update(context: ControlUiViewContext<ControlUiSurfaceProps["transcript"]>) {
          const empty = context.props.agentId === "director" &&
            !context.props.loading && !context.props.stream &&
            context.props.messages.length === 0;
          if (!empty) {
            welcome?.remove();
            welcome = undefined;
            disposeDefault ??= context.mountDefault(container);
            return;
          }
          disposeDefault?.();
          disposeDefault = undefined;
          if (welcome) return;
          welcome = document.createElement("section");
          welcome.className = "agentlabs-welcome";
          const mark = document.createElement("div");
          mark.className = "agentlabs-mark";
          mark.textContent = "AL";
          mark.setAttribute("aria-hidden", "true");
          const title = document.createElement("h1");
          title.textContent = "AgentLabs";
          const subtitle = document.createElement("p");
          subtitle.textContent = "Cộng sự nghiên cứu AI/ML của bạn.";
          const detail = document.createElement("p");
          detail.className = "agentlabs-welcome-detail";
          detail.textContent = "Trao đổi ý tưởng, đọc repo local, thiết kế thực nghiệm và viết paper.\nChat như bình thường; giao việc nghiên cứu khi bạn sẵn sàng.";
          welcome.append(mark, title, subtitle, detail);
          container.append(welcome);
        }
        update(initial);
        return {
          update,
          dispose() { disposeDefault?.(); welcome?.remove(); },
        };
      },
    });
    host.ui.selectReplacement("composer", "research-composer");
    host.ui.selectReplacement("transcript", "research-transcript");
    return () => {
      unregister();
      unregisterWelcome();
    };
  },
};
export default plugin;
