"""Content scheduler — runs the full pipeline on a cron schedule or on-demand."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_RUNS_DIR = Path(__file__).resolve().parents[1] / "runs"
_SCHEDULE_PATH = _RUNS_DIR / "schedule.json"


def _load_schedule_state() -> dict[str, Any]:
    if _SCHEDULE_PATH.exists():
        try:
            return json.loads(_SCHEDULE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"enabled": False, "cron": "", "last_run": None, "last_result": None}


def _save_schedule_state(state: dict[str, Any]) -> None:
    _RUNS_DIR.mkdir(exist_ok=True)
    _SCHEDULE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def _split_blog_and_social(text: str) -> tuple[str, str]:
    """Split combined 'Run All' output into blog and social sections."""
    blog = ""
    social = ""
    if "## Social" in text:
        parts = text.split("## Social", 1)
        blog_part = parts[0]
        social = parts[1] if len(parts) > 1 else ""
        if blog_part.startswith("## Blog"):
            blog = blog_part[len("## Blog"):].strip()
        else:
            blog = blog_part.strip()
    elif "## Blog" in text:
        blog = text.split("## Blog", 1)[1].strip() if "## Blog" in text else text
    else:
        blog = text
    return blog, social


def execute_scheduled_run() -> dict[str, Any]:
    """Execute a single autonomous pipeline run: topic gen -> pipeline -> publish.

    Returns a dict with run metadata.
    """
    from x3p_content_manager.app.brand_intel import load_brand_snapshot, refresh_brand_snapshot
    from x3p_content_manager.app.pipeline import run_pipeline_with_quality_gate
    from x3p_content_manager.crew import X3PCareContentCrew
    from x3p_content_manager.main import default_inputs, load_default_brand_guide
    from x3p_content_manager.memory import remember_run
    from x3p_content_manager.postprocess import sanitize_outputs
    from x3p_content_manager.seo_schema import save_seo_meta
    from x3p_content_manager.supabase_publisher import SupabasePublisher
    from x3p_content_manager.topic_generator import generate_next_topic

    run_result: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ok": False,
        "topic": "",
        "published_slug": None,
        "social_count": 0,
        "error": None,
    }

    try:
        # 1. Refresh brand intel
        brand_snapshot = load_brand_snapshot()
        brand_data = brand_snapshot.data if hasattr(brand_snapshot, "data") else {}

        # 2. Generate topic
        topic_suggestion = generate_next_topic(
            brand_snapshot=brand_data,
            trend_brief=None,
        )
        run_result["topic"] = topic_suggestion.topic
        logger.info("Scheduled run topic: %s (source: %s)", topic_suggestion.topic, topic_suggestion.source)

        # 3. Build inputs
        inputs = default_inputs()
        inputs["topic"] = topic_suggestion.topic
        inputs["audience"] = topic_suggestion.audience
        inputs["tone"] = topic_suggestion.tone
        if topic_suggestion.angle:
            inputs["angle_choice"] = topic_suggestion.angle

        # 4. Run full pipeline
        crew = X3PCareContentCrew()
        text, payload, usage, warnings = run_pipeline_with_quality_gate(
            crew, "Run All", inputs, variants=1, progress=None,
        )

        if not (isinstance(text, str) and text.strip()):
            raise RuntimeError("Pipeline returned empty output")

        # 5. Post-process
        sanitize_outputs("all")

        # 6. Save locally
        outputs_dir = Path("outputs/all")
        outputs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = outputs_dir / f"scheduled_{ts}.md"
        md_path.write_text(text, encoding="utf-8")

        # 7. Save SEO meta
        blog_text, social_text = _split_blog_and_social(text)
        if blog_text:
            save_seo_meta(blog_text)

        # 8. Publish to Supabase
        publisher = SupabasePublisher()
        if publisher.is_configured():
            if blog_text:
                blog_result = publisher.publish_blog(blog_text)
                if blog_result.ok:
                    run_result["published_slug"] = blog_result.slug
                    logger.info("Published blog: %s", blog_result.slug)

                    if social_text:
                        social_result = publisher.publish_social(social_text, blog_result.blog_id)
                        if social_result.ok:
                            run_result["social_count"] = len(social_result.social_ids)
                else:
                    logger.warning("Blog publish failed: %s", blog_result.error)
        else:
            logger.info("Supabase not configured, skipping publish")

        # 9. Remember run
        remember_run("scheduled_run_all", inputs, text)

        run_result["ok"] = True
        run_result["finished_at"] = datetime.now(timezone.utc).isoformat()

    except Exception as exc:
        run_result["ok"] = False
        run_result["error"] = str(exc)
        run_result["finished_at"] = datetime.now(timezone.utc).isoformat()
        logger.error("Scheduled run failed: %s", exc)

    # Update schedule state
    state = _load_schedule_state()
    state["last_run"] = run_result["started_at"]
    state["last_result"] = run_result
    _save_schedule_state(state)

    return run_result


class ContentScheduler:
    """Manages scheduled content generation runs."""

    def __init__(self) -> None:
        self._scheduler: Any = None

    def _get_scheduler(self) -> Any:
        if self._scheduler is not None:
            return self._scheduler
        from apscheduler.schedulers.background import BackgroundScheduler

        self._scheduler = BackgroundScheduler(timezone="UTC")
        return self._scheduler

    def schedule_recurring(self, cron_expression: str) -> None:
        """Set up a recurring content generation schedule.

        Args:
            cron_expression: 5-field cron string (minute hour day month weekday)
        """
        parts = cron_expression.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expression}")

        scheduler = self._get_scheduler()
        # Remove existing job if any
        try:
            scheduler.remove_job("cmo_scheduled_run")
        except Exception:
            pass

        from apscheduler.triggers.cron import CronTrigger

        trigger = CronTrigger.from_crontab(cron_expression)
        scheduler.add_job(
            execute_scheduled_run,
            trigger=trigger,
            id="cmo_scheduled_run",
            name="CMO Scheduled Content Run",
            replace_existing=True,
        )

        state = _load_schedule_state()
        state["enabled"] = True
        state["cron"] = cron_expression
        _save_schedule_state(state)

        logger.info("Scheduled recurring runs with cron: %s", cron_expression)

    def run_once(self) -> dict[str, Any]:
        """Execute a single autonomous run immediately."""
        return execute_scheduled_run()

    def start(self) -> None:
        """Start the scheduler with the saved cron expression."""
        state = _load_schedule_state()
        cron = state.get("cron", "").strip()
        if not cron:
            cron = os.getenv("CMO_SCHEDULE_CRON", "").strip()
        if not cron:
            logger.error("No cron expression configured. Set CMO_SCHEDULE_CRON or use schedule_recurring().")
            return

        self.schedule_recurring(cron)
        scheduler = self._get_scheduler()
        scheduler.start()
        logger.info("Scheduler started. Press Ctrl+C to stop.")

        try:
            import time

            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()
            logger.info("Scheduler stopped.")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        state = _load_schedule_state()
        state["enabled"] = False
        _save_schedule_state(state)

    @staticmethod
    def get_schedule_status() -> dict[str, Any]:
        """Return current schedule state."""
        return _load_schedule_state()


def main() -> None:
    """CLI entry point for the scheduler."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m x3p_content_manager.scheduler [start|run-once|status]")
        sys.exit(1)

    command = sys.argv[1].lower().strip()

    if command == "start":
        ContentScheduler().start()
    elif command == "run-once":
        result = ContentScheduler().run_once()
        print(json.dumps(result, indent=2, default=str))
    elif command == "status":
        status = ContentScheduler.get_schedule_status()
        print(json.dumps(status, indent=2, default=str))
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
