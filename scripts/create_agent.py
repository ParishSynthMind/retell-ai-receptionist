"""Create (or update, or delete) the receptionist's Retell LLM and agent through Retell's API.

  python scripts/create_agent.py --server-url https://your-host --dry-run   # print both bodies, no API call
  python scripts/create_agent.py --server-url https://your-host             # create, ids saved to var/retell_ids.json
  python scripts/create_agent.py --server-url https://your-host --update    # push prompt/tool changes to the same ids
  python scripts/create_agent.py --delete                                   # remove the agent and the LLM

The API key comes from RETELL_API_KEY, or from the macOS Keychain with --keychain SERVICE.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from receptionist.agent import build_agent, build_llm  # noqa: E402
from receptionist.config import Settings  # noqa: E402
from receptionist.retell_api import RetellAPI, RetellError  # noqa: E402


def api_key(keychain: str | None, account: str) -> str:
    if keychain:
        proc = subprocess.run(["security", "find-generic-password", "-a", account, "-s", keychain, "-w"],
                              capture_output=True, text=True)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise SystemExit(f"Keychain item {keychain!r} (account {account!r}) not found")
        return proc.stdout.strip()
    key = os.environ.get("RETELL_API_KEY")
    if not key:
        raise SystemExit("Set RETELL_API_KEY, or pass --keychain SERVICE")
    return key


def main(argv=None, api=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server-url", help="public https base URL of this service")
    p.add_argument("--dry-run", action="store_true", help="print the request bodies and stop")
    p.add_argument("--update", action="store_true", help="update the LLM and agent in the ids file")
    p.add_argument("--delete", action="store_true", help="delete the LLM and agent in the ids file")
    p.add_argument("--ids-file", default=str(ROOT / "var" / "retell_ids.json"))
    p.add_argument("--voice-id", default="retell-Cimo")
    p.add_argument("--keychain", help="read the API key from this Keychain item instead of the environment")
    p.add_argument("--keychain-account", default=os.environ.get("RETELL_KEYCHAIN_ACCOUNT", "neo"))
    a = p.parse_args(argv)
    ids_file = Path(a.ids_file)
    s = Settings.from_env()

    if a.delete:
        ids = json.loads(ids_file.read_text())
        api = api or RetellAPI(api_key(a.keychain, a.keychain_account))
        api.delete_agent(ids["agent_id"])
        api.delete_llm(ids["llm_id"])
        ids_file.unlink()
        print(f"deleted agent {ids['agent_id']} and LLM {ids['llm_id']}")
        return 0

    if not a.server_url:
        p.error("--server-url is needed")
    llm_body = build_llm(s.business_name, s.timezone, s.knowledge_base, a.server_url)
    if a.dry_run:
        print("POST /create-retell-llm\n" + json.dumps(llm_body, indent=2))
        print("\nPOST /create-agent\n" + json.dumps(build_agent("<llm_id from the first call>", a.server_url,
                                                                voice_id=a.voice_id), indent=2))
        return 0

    api = api or RetellAPI(api_key(a.keychain, a.keychain_account))
    try:
        if a.update:
            ids = json.loads(ids_file.read_text())
            llm = api.update_llm(ids["llm_id"], llm_body)
            agent = api.update_agent(ids["agent_id"], build_agent(ids["llm_id"], a.server_url, voice_id=a.voice_id))
        else:
            llm = api.create_llm(llm_body)
            agent = api.create_agent(build_agent(llm["llm_id"], a.server_url, voice_id=a.voice_id))
            ids_file.parent.mkdir(parents=True, exist_ok=True)
            ids_file.write_text(json.dumps({"llm_id": llm["llm_id"], "agent_id": agent["agent_id"]}, indent=2))
    except RetellError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"LLM {llm['llm_id']} (version {llm.get('version')}), agent {agent['agent_id']} "
          f"(version {agent.get('version')}); ids in {ids_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
