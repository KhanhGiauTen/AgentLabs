# OpenClaw local + research harness

**Distribution mặc định hiện là native OpenClaw**, UI port 18790 và model proxy 18791.
Dùng `agentlabs.ps1 start` / `agentlabs.ps1 dashboard`; hướng dẫn đầy đủ ở
[native README](../native/README.md) và [thiết kế V2](NATIVE_RESEARCH_DESIGN.md).
State riêng: `D:\ResearchLab\work\agentlabs-native`.

Phần còn lại bên dưới mô tả **adapter của prototype V1** trên 8765/18789;
không dùng các lệnh bridge này thay cho launcher native.

## Cấu trúc trên ổ D

```text
D:\ResearchLab\
  openclaw\                    # source upstream, clone shallow, full working tree
  reference-agent-laboratory\   # source tham khảo, không chạy experiment upstream
  research-studio\              # harness Python/React do phiên này tạo
  work\
    .venv\                     # Python environment hiện đang dùng
    openclaw-runtime\          # package release chính thức + production deps
    openclaw-state\            # profile/state/config riêng cho lab
    npm-cache\
    tmp\
```

OpenClaw source: tag `v2026.10.7`, commit `157d8c2bc3ea2fa183afdc11088e69690bf8e64e`, MIT. AgentLaboratory reference: commit `d9017d90e329112d2a80b7712f37ee9094d2cd27`, MIT. Nguồn: [OpenClaw](https://github.com/openclaw/openclaw), [AgentLaboratory](https://github.com/SamuelSchmidgall/AgentLaboratory).

Đang dùng **runtime release đã build sẵn**, không biên dịch toàn bộ OpenClaw monorepo. Đây là lựa chọn giảm dependency phát triển và giữ engine trùng release pin. Bạn vẫn có toàn bộ working tree để đọc/chỉnh về sau. Source harness là code độc lập, không patch `node_modules` hoặc internals OpenClaw.

## Chạy đã cài

```powershell
cd D:\ResearchLab\research-studio
.\scripts\openclaw.ps1 -Action version
.\scripts\openclaw.ps1 -Action validate
.\scripts\openclaw.ps1 -Action start
```

Terminal thứ hai:

```powershell
cd D:\ResearchLab\research-studio
.\start.ps1
```

`start` chạy foreground, Ctrl+C để dừng. Không cài daemon/service. Không dùng `--force` để giành port từ tiến trình khác. Nếu port 18789 đang bận, kiểm tra app sở hữu port trước khi xử lý.

Runtime Node được chọn theo thứ tự `RESEARCH_NODE`, runtime tương thích đi kèm Codex, rồi Node trong PATH. Trên máy hiện tại dùng Node `24.22.1`; Node `24.16.0` mặc định trong PATH không đáp ứng package OpenClaw đã pin. Script điều chỉnh PATH **chỉ trong child process** để lifecycle scripts dùng đúng Node; không thay Node global.

## `.env` của lab

`scripts/openclaw.py setup` tạo token gateway local trong `.env`, không in token. Chỉ token local được tự tạo; API key model do bạn cấp bằng editor local.

```dotenv
OPENAI_API_KEY=
OPENCLAW_URL=http://127.0.0.1:18789
OPENCLAW_AGENT=research
OPENCLAW_CHEAP_MODEL=openai/gpt-6-luna
OPENCLAW_CALL_RESERVE_USD=0.10
```

Để các vai trò thường dùng model free:

```dotenv
GATEWAY_API_KEY=
GATEWAY_MODEL=<available-tool-capable-model>:free
OPENCLAW_CHEAP_MODEL=openrouter/<available-tool-capable-model>:free
```

Điền ID thật từ dashboard, không để nguyên placeholder. Hai bước Methods/Chair vẫn dùng OpenAI Sol trong mode OpenClaw. Script chuyển `GATEWAY_API_KEY` sang biến môi trường `OPENROUTER_API_KEY` cho runtime. Sửa `.env` xong cần dừng cả backend/gateway của lab, chạy `setup` để cập nhật profile nếu đổi model, rồi khởi động lại. Không sửa state/config trong lúc gateway đang có tác vụ ghi.

## Cấu hình riêng, quyền rõ ràng

- `OPENCLAW_STATE_DIR` và `OPENCLAW_CONFIG_PATH` trỏ vào `D:\ResearchLab\work\openclaw-state`; không ghi vào hồ sơ global `~/.openclaw`.
- Bind loopback, auth token, endpoint `/v1/responses` bật rõ ràng.
- Native tools `deny:["*"]`, browser tắt, cron/heartbeat tắt, memory slot `none`; chỉ allow plugin provider OpenAI/OpenRouter.
- Không cấu hình Telegram/WhatsApp/Slack, không gửi tin nhắn hay kết nối tài khoản chat.
- `fallbacks:[]`; không tự nâng model khi hết quota.
- Auto-compaction tắt trong profile này để giảm model call ngầm; harness tự giới hạn context. Token giới hạn ở gateway vẫn là best effort.
- Temp, log và npm cache của các lần chạy qua script đã trỏ sang D.

Không dùng gateway bearer token như API token hẹp: tài liệu OpenClaw coi nó là quyền operator rộng. Chỉ backend giữ token, URL gateway phải là loopback; không public endpoint. Nguồn: [OpenResponses contract](https://docs.openclaw.ai/gateway/openresponses-http-api), [HTTP auth/routing](https://docs.openclaw.ai/gateway/openai-http-api).

## Hợp đồng adapter

Harness gửi model target `openclaw/research`, header `x-openclaw-model` xác định provider/model của role, `instructions` cho vai trò, bounded `input` và các client function definitions. OpenClaw trả `function_call`; harness chạy tool sau khi kiểm tra policy và gửi `function_call_output` ở lượt sau. Cách này dùng API công khai được tài liệu hóa, không gọi module nội bộ.

R1/R2/R3 là node riêng ở harness. Gateway hiện có một agent target `research`, không giả vờ tạo 10 gateway hoặc nhiều OpenClaw agent đã cấu hình. Ba review được fan-out ở graph; runtime có thể serialize request theo giới hạn `maxConcurrent=1` để tránh quá tải. Muốn tăng concurrency cần đo latency/quota thực tế trước.

## Cài lại runtime hoặc tự build source

Với dependency Python đã cài:

```powershell
.\scripts\openclaw.ps1 -Action install
.\scripts\openclaw.ps1 -Action validate
```

Script install pin `openclaw@2026.10.7`, không dùng `latest` và không nâng runtime đang chạy. Không tự cập nhật production profile.

Nếu mục tiêu là sửa code engine upstream, dừng gateway, tạo nhánh ở checkout source rồi làm theo README/AGENTS upstream và dùng pnpm. Các lệnh build dưới đây là hướng dẫn, **chưa chạy trong phiên này**:

```powershell
cd D:\ResearchLab\openclaw
# Với đúng Node được yêu cầu bởi package.json
pnpm install --frozen-lockfile
pnpm build
pnpm ui:build
```

Nguồn cài/build: [README OpenClaw](https://github.com/openclaw/openclaw), [source setup](https://docs.openclaw.ai/start/setup). Không thay runtime release đang hoạt động bằng build chưa test.

## Kết quả vận hành quan sát được

CLI báo `OpenClaw 2026.10.7 (157d8c2)`, profile qua `config validate`, `gateway health` trả OK và GET `/v1/models` authenticated trả ba target `openclaw`, `openclaw/default`, `openclaw/research`. Sau khi thu hẹp plugins, gateway đã báo ready với memory/heartbeat tắt.

Cold start đầu tiên chậm đáng kể trên Windows, có cảnh báo nội bộ ở cấu hình nhiều plugin mặc định; profile sau đó thu hẹp còn provider cần thiết. Một lần CLI validation kết thúc có thông báo cleanup timeout dù exit code 0. Không suy ra mọi chức năng engine ổn định chỉ từ health check. Tác vụ suy luận thật và client tool roundtrip qua engine chưa được xác minh với model key; adapter được kiểm thử bằng transport giả lập.
