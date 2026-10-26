"""Private stdin/JSON worker. Model code runs only in an approved offline container."""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


async def capture(process, limit=60000):
    async def read(stream):
        chunks, size = [], 0
        while chunk := await stream.read(8192):
            if size < limit:
                chunks.append(chunk[: limit - size])
            size += len(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    output = await asyncio.gather(read(process.stdout), read(process.stderr))
    await process.wait()
    return output


def docker_args(scratch, name, image):
    return [
        "docker",
        "run",
        "--pull=never",
        "--rm",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=64",
        "--memory=1g",
        "--memory-swap=1g",
        "--cpus=2",
        "--user=65534:65534",
        "--ulimit",
        "fsize=1024:1024",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--mount",
        f"type=bind,source={scratch},target=/workspace",
        "-w",
        "/workspace",
        "-e",
        "MPLCONFIGDIR=/tmp/mpl",
        "-e",
        "OPENBLAS_NUM_THREADS=2",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        image,
        "python",
        "-B",
        "experiment.py",
    ]


async def run(request):
    code = request["code"].encode("utf-8")
    if len(code) > 160000 or hashlib.sha256(code).hexdigest() != request["code_hash"]:
        raise ValueError("Approved code hash mismatch or code too large")
    # No model-supplied image, executable, path or extra container flags.
    image = os.environ.get("SANDBOX_IMAGE", "research-studio-sandbox:local")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,200}", image):
        raise ValueError("Invalid configured sandbox image name")
    status = await asyncio.create_subprocess_exec(
        "docker",
        "info",
        "--format",
        "{{.ServerVersion}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(status.communicate(), 6)
    except asyncio.TimeoutError:
        status.kill()
        await status.wait()
        raise ValueError("Docker engine did not respond")
    if status.returncode:
        raise ValueError("Docker engine is off; start Docker Desktop and build sandbox image")
    with tempfile.TemporaryDirectory(prefix="agentlabs-native-") as folder:
        scratch = Path(folder)
        (scratch / "experiment.py").write_bytes(code)
        name = "agentlabs-native-" + uuid.uuid4().hex[:16]
        process = await asyncio.create_subprocess_exec(
            *docker_args(scratch, name, image),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(capture(process), 120)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # Remove only the exact container created by this invocation.
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise ValueError("Experiment interrupted or exceeded 120 seconds")
        artifacts = {"stdout.txt": out, "stderr.txt": err}
        metrics = scratch / "metrics.json"
        # The container has exited. Only one bounded regular output is imported.
        if metrics.exists() and not metrics.is_symlink() and metrics.is_file():
            if metrics.stat().st_size <= 60000:
                raw = metrics.read_text(encoding="utf-8")
                json.loads(raw)
                artifacts["metrics.json"] = raw
        result = {
            "status": "completed" if process.returncode == 0 else "error",
            "exit_code": process.returncode,
            "scope": "offline CPU smoke experiment; no datasets mounted",
            "artifacts": artifacts,
        }
        artifacts["execution.json"] = json.dumps(
            {k: v for k, v in result.items() if k != "artifacts"}
        )
        return result


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(200001)
        if len(raw) > 200000:
            raise ValueError("Worker input too large")
        answer = asyncio.run(run(json.loads(raw)))
    except Exception as exc:
        answer = {"status": "error", "message": str(exc)[:1000], "artifacts": {}}
    sys.stdout.buffer.write(json.dumps(answer, ensure_ascii=True).encode("utf-8"))
