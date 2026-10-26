import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { registerResearch } from "./runtime.mjs";

export default definePluginEntry({
  id: "agentlabs-research",
  name: "AgentLabs Research",
  description:
    "Bounded research phases, durable artifacts and independent review gates.",
  register: registerResearch,
});
