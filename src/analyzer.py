"""
Analyzer — Silver/Gold Tier Brain
Reads Needs_Action/*.md files, uses LLM to:
  1. Classify priority (high / medium / low)
  2. Draft contextual responses for high-priority items
  3. Move files through the vault workflow

Supports: Claude (ANTHROPIC_API_KEY) or Gemini (GEMINI_API_KEY)
Set LLM_PROVIDER=claude (default) or LLM_PROVIDER=gemini in .env
"""
import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Analyzer] %(levelname)s: %(message)s",
)
logger = logging.getLogger("Analyzer")

# ── LLM Prompts ───────────────────────────────────────────────────────────────

CLASSIFY_SYSTEM = (
    "You are an AI assistant for Alishba Nasir, a professional web developer. "
    "Analyze notifications/messages and classify them. "
    "Respond ONLY with valid JSON — no markdown fences, no extra text."
)

CLASSIFY_PROMPT = """Analyze this notification/message and classify it.

CONTENT:
{content}

Return exactly this JSON structure:
{{
  "priority": "high" | "medium" | "low",
  "category": "job_opportunity" | "direct_message" | "connection_request" | "newsletter" | "promotion" | "platform_update" | "other",
  "reason": "one sentence explaining why",
  "needs_response": true | false,
  "suggested_action": "brief action description"
}}

Rules:
- high   = job offers, interview invites, direct messages from real people, project queries
- medium = connection requests from relevant professionals, important platform alerts
- low    = newsletters, promotions, marketing digests, generic platform notifications"""

DRAFT_SYSTEM = (
    "You are Alishba Nasir's AI assistant. "
    "Draft professional, concise responses on her behalf. "
    "Write in first person as Alishba. Be warm but professional. "
    "Keep responses to 3-5 sentences. Never mention being an AI."
)

DRAFT_PROMPT = """Draft a response to this message on behalf of Alishba Nasir.

=== ALISHBA'S PROFILE ===
{profile}

=== MESSAGE ===
{content}

=== CONTEXT ===
Category: {category}
Reason for priority: {reason}

Instructions:
- Job opportunity → express interest, highlight 2-3 relevant skills, ask for next steps
- Direct message  → acknowledge warmly, respond helpfully
- Connection      → accept and send a brief professional note"""


# ── LLM Clients ───────────────────────────────────────────────────────────────

def _call_claude(prompt: str, system: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _call_gemini(prompt: str, system: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system),
    )
    return response.text


def _call_llm(prompt: str, system: str) -> str:
    provider = os.getenv("LLM_PROVIDER", "claude").lower()
    if provider == "gemini":
        return _call_gemini(prompt, system)
    return _call_claude(prompt, system)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_profile(vault: Path) -> str:
    p = vault / "Profile.md"
    return p.read_text(encoding="utf-8") if p.exists() else "Professional web developer. Respond professionally."


def _parse_md(file_path: Path) -> dict:
    """Parse frontmatter + body from a vault markdown file."""
    text = file_path.read_text(encoding="utf-8")
    frontmatter, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                frontmatter[k.strip()] = v.strip().strip('"').strip("'")
        body = m.group(2).strip()
    return {"frontmatter": frontmatter, "body": body}


def _strip_fences(text: str) -> str:
    return re.sub(r"```[a-z]*\n?|```\n?", "", text).strip()


# ── Core Logic ────────────────────────────────────────────────────────────────

def classify_item(content: str) -> dict:
    try:
        raw = _call_llm(CLASSIFY_PROMPT.format(content=content[:2000]), CLASSIFY_SYSTEM)
        return json.loads(_strip_fences(raw))
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        return {
            "priority": "medium",
            "category": "other",
            "reason": "Auto-classification failed — manual review needed",
            "needs_response": False,
            "suggested_action": "Review manually",
        }


def draft_response(content: str, classification: dict, profile: str) -> str:
    prompt = DRAFT_PROMPT.format(
        profile=profile[:1500],
        content=content[:1500],
        category=classification.get("category", ""),
        reason=classification.get("reason", ""),
    )
    try:
        return _call_llm(prompt, DRAFT_SYSTEM)
    except Exception as e:
        logger.error(f"Draft generation failed: {e}")
        return "[Draft generation failed — please write response manually]"


# ── Analyzer Class ────────────────────────────────────────────────────────────

class Analyzer:
    def __init__(self, vault_path: str, dry_run: bool = False):
        self.vault = Path(vault_path).resolve()
        self.needs_action    = self.vault / "Needs_Action"
        self.plans           = self.vault / "Plans"
        self.done            = self.vault / "Done"
        self.pending_approval = self.vault / "Pending_Approval"
        self.briefings       = self.vault / "Briefings"
        self.logs_dir        = self.vault / "Logs"
        self.dry_run         = dry_run
        self.profile         = _load_profile(self.vault)

        for d in [self.plans, self.done, self.pending_approval, self.briefings, self.logs_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, action: str, details: dict):
        log_file = self.logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json"
        entry = {"timestamp": datetime.now().isoformat(), "actor": "analyzer", "action": action, **details}
        existing = []
        if log_file.exists():
            try:
                existing = json.loads(log_file.read_text())
            except Exception:
                pass
        existing.append(entry)
        if not self.dry_run:
            log_file.write_text(json.dumps(existing, indent=2))

    # ── File Writers ──────────────────────────────────────────────────────────

    def _write_plan(self, source: Path, body: str, cls: dict, draft: Optional[str]) -> Path:
        now = datetime.now()
        plan_path = self.plans / f"PLAN_{source.stem}_{now.strftime('%H%M%S')}.md"
        lines = [
            "---",
            f"source_file: {source.name}",
            f"priority: {cls['priority']}",
            f"category: {cls['category']}",
            f"needs_response: {str(cls['needs_response']).lower()}",
            f"analyzed_at: {now.isoformat()}",
            "status: analyzed",
            "---",
            "",
            "## AI Analysis",
            "",
            f"**Priority:** `{cls['priority'].upper()}`  ",
            f"**Category:** `{cls['category']}`  ",
            f"**Reason:** {cls['reason']}  ",
            f"**Suggested Action:** {cls['suggested_action']}",
            "",
            "## Original Content",
            "",
            body[:1200],
        ]
        if draft:
            lines += ["", "## Draft Response", "", draft, "", "---", "*Awaiting approval in /Pending_Approval/*"]
        if not self.dry_run:
            plan_path.write_text("\n".join(lines), encoding="utf-8")
        return plan_path

    def _write_pending_approval(self, source: Path, cls: dict, draft: str) -> Path:
        now = datetime.now()
        p = self.pending_approval / f"APPROVE_{source.stem}_{now.strftime('%H%M%S')}.md"
        content = f"""---
source_file: {source.name}
action_type: send_response
priority: {cls['priority']}
category: {cls['category']}
created_at: {now.isoformat()}
status: pending_approval
---

## Action Required — Human Approval Needed

**Priority:** `{cls['priority'].upper()}`
**Category:** `{cls['category']}`
**Why this needs a response:** {cls['reason']}

---

## Draft Response (Edit if needed, then approve)

{draft}

---

## Instructions
1. Edit the draft above if needed
2. Move this file to `/Approved/` to send the response
3. Move to `/Rejected/` to discard
"""
        if not self.dry_run:
            p.write_text(content, encoding="utf-8")
        return p

    # ── Process Single File ───────────────────────────────────────────────────

    def process_file(self, file_path: Path) -> str:
        """Analyze one file, return its priority string."""
        logger.info(f"Analyzing: {file_path.name}")

        parsed = _parse_md(file_path)
        body = parsed["body"]

        # Step 1 — Classify
        cls = classify_item(body)
        priority = cls.get("priority", "low")
        logger.info(f"  Priority: {priority.upper()} | Category: {cls.get('category')} | {cls.get('reason','')}")

        # Step 2 — Draft if high priority and response needed
        draft = None
        if priority == "high" and cls.get("needs_response"):
            logger.info("  Drafting response...")
            draft = draft_response(body, cls, self.profile)

        if not self.dry_run:
            # Always write a plan
            plan = self._write_plan(file_path, body, cls, draft)
            logger.info(f"  Plan saved: {plan.name}")

            # Write to Pending_Approval if draft exists
            if draft:
                approval = self._write_pending_approval(file_path, cls, draft)
                logger.info(f"  Draft saved for approval: {approval.name}")

            # Move original: low/medium (no response) → Done; high → stays in Needs_Action
            if priority == "low" or (priority != "high" and not cls.get("needs_response")):
                dest = self.done / file_path.name
                file_path.rename(dest)
                logger.info(f"  Moved to Done.")

        self._log("analyzed", {
            "file": file_path.name,
            "priority": priority,
            "category": cls.get("category"),
            "draft_created": draft is not None,
            "dry_run": self.dry_run,
        })

        return priority

    # ── Process All ───────────────────────────────────────────────────────────

    def process_all(self, file_list: Optional[list] = None) -> dict:
        """Process all (or a specific list of) files in Needs_Action."""
        if file_list:
            files = [Path(f) for f in file_list if Path(f).exists()]
        else:
            files = [f for f in self.needs_action.glob("*.md") if f.name != ".gitkeep"]

        if not files:
            logger.info("No items to process in Needs_Action.")
            return {"high": 0, "medium": 0, "low": 0, "total": 0}

        logger.info(f"Processing {len(files)} item(s)...")
        counts = {"high": 0, "medium": 0, "low": 0}

        for f in files:
            try:
                p = self.process_file(f)
                counts[p] = counts.get(p, 0) + 1
            except Exception as e:
                logger.error(f"Error processing {f.name}: {e}")

        counts["total"] = len(files)
        logger.info(f"Complete — High: {counts['high']} | Medium: {counts['medium']} | Low: {counts['low']}")

        self._write_summary_report(counts, files)
        return counts

    # ── Summary Report ────────────────────────────────────────────────────────

    def _write_summary_report(self, counts: dict, files: list):
        now = datetime.now()
        report = self.briefings / f"Analysis_{now.strftime('%Y-%m-%d_%H%M%S')}.md"
        body = f"""# Analysis Report — {now.strftime('%Y-%m-%d %H:%M')}

## Summary

| Priority | Count |
|----------|-------|
| High (drafts in /Pending_Approval) | {counts.get('high', 0)} |
| Medium | {counts.get('medium', 0)} |
| Low (moved to /Done) | {counts.get('low', 0)} |
| **Total** | **{counts['total']}** |

## Items Processed

"""
        for f in files:
            body += f"- `{f.name}`\n"
        body += "\n---\n*Generated by AI Employee Analyzer — Silver/Gold Tier*\n"

        if not self.dry_run:
            report.write_text(body, encoding="utf-8")
            logger.info(f"Summary report: {report.name}")


# ── Entry Point ───────────────────────────────────────────────────────────────

def _load_dotenv(root: Path):
    env = root / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def main():
    _load_dotenv(Path(__file__).parent.parent)

    parser = argparse.ArgumentParser(description="AI Employee Analyzer — Silver/Gold Tier")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    parser.add_argument("--dry-run", action="store_true", help="Log intent only, don't move files")
    parser.add_argument("--file", help="Analyze a single specific file path")
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("GEMINI_API_KEY"):
        logger.error("No LLM API key found. Set ANTHROPIC_API_KEY or GEMINI_API_KEY in .env")
        sys.exit(1)

    analyzer = Analyzer(args.vault, dry_run=args.dry_run)

    if args.file:
        analyzer.process_file(Path(args.file))
    else:
        analyzer.process_all()


if __name__ == "__main__":
    main()
