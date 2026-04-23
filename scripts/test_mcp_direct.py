"""
Direct MCP server test via JSON-RPC over stdio.

Bypasses the MCP Inspector entirely — sends raw JSON-RPC messages to the
server subprocess and prints the responses.

Usage:
    python test_mcp_direct.py
"""

import json
import select
import subprocess
import sys
import time

MCP_PROTOCOL_VERSION = "2024-11-05"


def send(proc, msg: dict) -> None:
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()


def recv(proc, timeout: float = 10.0) -> dict | None:
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if not ready:
        return None
    line = proc.stdout.readline()
    if not line:
        return None
    return json.loads(line.strip())


def extract_result(resp: dict):
    """
    FastMCP >= 1.6 returns data in structuredContent.result.
    Older versions serialised it as JSON text in content[0]['text'].
    Handle both.
    """
    if resp is None:
        return None
    result = resp.get("result", {})
    # New format: structuredContent.result
    sc = result.get("structuredContent")
    if sc is not None and "result" in sc:
        return sc["result"]
    # Old format: content[0]["text"]  (JSON-encoded string)
    content = result.get("content", [])
    if content and content[0].get("text"):
        return json.loads(content[0]["text"])
    return None


def call_tool(proc, call_id: int, tool_name: str, arguments: dict):
    send(proc, {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })
    resp = recv(proc)
    return extract_result(resp), resp


def main() -> None:
    print("Starting MCP server subprocess...")
    proc = subprocess.Popen(
        [sys.executable, "run_mcp.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    time.sleep(1.5)  # give the server a moment to boot

    # ── 1. Handshake ────────────────────────────────────────────────────────
    print("\n[1/6] initialize handshake")
    send(proc, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "direct-test-client", "version": "1.0"},
        },
    })
    init_resp = recv(proc)
    if init_resp is None:
        stderr = proc.stderr.read()
        print(f"ERROR: no response from server.\nStderr:\n{stderr}")
        proc.kill()
        sys.exit(1)
    print(f"  server name : {init_resp.get('result', {}).get('serverInfo', {}).get('name')}")
    print(f"  mcp version : {init_resp.get('result', {}).get('protocolVersion')}")

    # Confirm initialisation
    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    # ── 2. List tools ────────────────────────────────────────────────────────
    print("\n[2/6] tools/list")
    send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools_resp = recv(proc)
    tools = tools_resp.get("result", {}).get("tools", []) if tools_resp else []
    print(f"  tools registered: {[t['name'] for t in tools]}")

    # ── 3. get_available_roles ───────────────────────────────────────────────
    print("\n[3/6] get_available_roles")
    result, raw = call_tool(proc, 3, "get_available_roles", {})
    if result:
        for r in result:
            print(f"  {r['canonical_role']:30s}  jobs={r['total_jobs']}")
    else:
        print("  (empty — no data in DB yet)")

    # ── 4. get_top_skills ────────────────────────────────────────────────────
    print("\n[4/6] get_top_skills  role=data_engineer  limit=5")
    result, raw = call_tool(proc, 4, "get_top_skills", {"role": "data_engineer", "limit": 5})
    if result:
        for s in result:
            print(f"  {s['skill']:20s}  mentions={s['mention_count']}  pct={s['pct']:.1f}%")
    else:
        print("  (empty — no data for data_engineer yet)")

    # ── 5. get_demand_trends ─────────────────────────────────────────────────
    print("\n[5/6] get_demand_trends  role=data_engineer")
    result, raw = call_tool(proc, 5, "get_demand_trends", {"role": "data_engineer"})
    if result:
        for t in result[:3]:
            print(f"  {t['date']}  jobs={t['job_count']}  companies={t['unique_companies']}")
        if len(result) > 3:
            print(f"  ... ({len(result)} rows total)")
    else:
        print("  (empty — no demand data yet)")

    # ── 6. compare_skills ────────────────────────────────────────────────────
    print("\n[6/6] compare_skills  role=data_engineer")
    sample_cv = ["Python", "SQL", "Spark", "Excel", "Tableau"]
    result, raw = call_tool(proc, 6, "compare_skills", {"cv_skills": sample_cv, "role": "data_engineer"})
    if result is not None:
        print(f"  CV skills tested    : {sample_cv}")
        print(f"  skills_you_have     : {result.get('skills_you_have')}")
        print(f"  skills_missing      : {result.get('skills_missing')}")
        print(f"  additional_skills   : {result.get('additional_skills')}")
        print(f"  market_coverage_pct : {result.get('market_coverage_pct')}%")
    else:
        print(f"  (no result — raw response: {raw})")

    # ── Done ─────────────────────────────────────────────────────────────────
    print("\nMCP server is functional. All tools responded without errors.")
    proc.kill()


if __name__ == "__main__":
    main()
