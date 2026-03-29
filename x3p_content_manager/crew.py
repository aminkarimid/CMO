from __future__ import annotations

import os
from pathlib import Path
from typing import List

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task, tool

from x3p_content_manager import tools


def _configure_crewai_storage() -> None:
    """Force CrewAI SQLite storage into a writable local folder."""
    try:
        storage_dir = Path.cwd() / "runs" / "crewai_storage"
        storage_dir.mkdir(parents=True, exist_ok=True)
        local_path = str(storage_dir)

        import crewai.memory.storage.kickoff_task_outputs_storage as _kickoff_store
        import crewai.utilities.paths as _paths

        def _local_db_storage_path() -> str:
            return local_path

        _paths.db_storage_path = _local_db_storage_path  # type: ignore[assignment]
        _kickoff_store.db_storage_path = _local_db_storage_path  # type: ignore[attr-defined]
    except Exception:
        pass


_configure_crewai_storage()


@CrewBase
class X3PCareContentCrew:
    """Focused X3P crew for blog + social + QA + intelligence pipelines."""

    agents: List[BaseAgent]
    tasks: List[Task]

    def _resolved_llm(self, configured_llm: str | None) -> str:
        configured = str(configured_llm or "").strip()
        backend = str(os.getenv("X3P_ACTIVE_BACKEND", "")).strip().lower()
        if backend == "openai":
            model = str(os.getenv("X3P_OPENAI_MODEL", "gpt-4o-mini")).strip() or "gpt-4o-mini"
            return model if model.startswith("openai/") else f"openai/{model}"
        if backend == "ollama":
            model = str(os.getenv("X3P_OLLAMA_MODEL", "llama3.1:8b")).strip() or "llama3.1:8b"
            return model if model.startswith("ollama/") else f"ollama/{model}"
        return configured

    def _agent_config(self, key: str) -> dict:
        config = dict(self.agents_config[key] or {})
        resolved_llm = self._resolved_llm(config.get("llm"))
        if resolved_llm:
            config["llm"] = resolved_llm
        return config

    # Agents
    @agent
    def strategist(self) -> Agent:
        return Agent(config=self._agent_config("strategist"), verbose=True)

    @agent
    def content_writer(self) -> Agent:
        return Agent(config=self._agent_config("content_writer"), verbose=True)

    @agent
    def editor(self) -> Agent:
        return Agent(config=self._agent_config("editor"), verbose=True)

    @agent
    def social_media_manager(self) -> Agent:
        return Agent(config=self._agent_config("social_media_manager"), verbose=True)

    @agent
    def fact_checker(self) -> Agent:
        return Agent(config=self._agent_config("fact_checker"), verbose=True)

    @agent
    def brand_guardian(self) -> Agent:
        return Agent(config=self._agent_config("brand_guardian"), verbose=True)

    @agent
    def brand_intel_analyst(self) -> Agent:
        return Agent(config=self._agent_config("brand_intel_analyst"), verbose=True)

    @agent
    def trend_intel_analyst(self) -> Agent:
        return Agent(config=self._agent_config("trend_intel_analyst"), verbose=True)

    # Tool bindings used by agents.yaml
    @tool
    def tavily_tool(self):
        return tools.tavily_tool

    @tool
    def social_trends_tool(self):
        return tools.social_trends_tool

    @tool
    def trend_verifier_tool(self):
        return tools.trend_verifier_tool

    @tool
    def x3p_site_snapshot_tool(self):
        return tools.x3p_site_snapshot_tool

    @tool
    def brand_retriever_tool(self):
        return tools.brand_retriever_tool

    # Tasks
    @task
    def topic_generation_task(self) -> Task:
        return Task(config=self.tasks_config["topic_generation_task"])

    @task
    def brand_intel_refresh_task(self) -> Task:
        return Task(
            config=self.tasks_config["brand_intel_refresh_task"],
            output_file="outputs/brand/x3p_brand_snapshot_brief.json",
        )

    @task
    def trend_brief_task(self) -> Task:
        return Task(
            config=self.tasks_config["trend_brief_task"],
            output_file="outputs/social/x3p_trend_brief.json",
        )

    @task
    def strategy_outline_task(self) -> Task:
        return Task(
            config=self.tasks_config["strategy_outline_task"],
            output_file="outputs/strategy/x3p_strategy_outline.md",
        )

    @task
    def writing_task(self) -> Task:
        return Task(
            config=self.tasks_config["writing_task"],
            output_file="outputs/blog/x3p_blog_draft.md",
        )

    @task
    def editing_task(self) -> Task:
        return Task(
            config=self.tasks_config["editing_task"],
            output_file="outputs/blog/x3p_blog_post.md",
        )

    @task
    def social_media_task(self) -> Task:
        return Task(
            config=self.tasks_config["social_media_task"],
            output_file="outputs/social/x3p_social_posts.md",
        )

    @task
    def fact_check_task(self) -> Task:
        return Task(
            config=self.tasks_config["fact_check_task"],
            output_file="outputs/factcheck/x3p_factcheck_report.md",
        )

    @task
    def brandcheck_task(self) -> Task:
        return Task(
            config=self.tasks_config["brandcheck_task"],
            output_file="outputs/brand/x3p_brandcheck_report.md",
        )

    # Crews
    @crew
    def brand_intel_crew(self) -> Crew:
        return Crew(
            agents=[self.brand_intel_analyst()],
            tasks=[self.brand_intel_refresh_task()],
            process=Process.sequential,
            memory=False,
            verbose=True,
        )

    @crew
    def trend_intel_crew(self) -> Crew:
        return Crew(
            agents=[self.trend_intel_analyst()],
            tasks=[self.trend_brief_task()],
            process=Process.sequential,
            memory=False,
            verbose=True,
        )

    @crew
    def blog_crew(self) -> Crew:
        return Crew(
            agents=[self.strategist(), self.content_writer(), self.editor()],
            tasks=[self.strategy_outline_task(), self.writing_task(), self.editing_task()],
            process=Process.sequential,
            memory=False,
            verbose=True,
        )

    @crew
    def social_crew(self) -> Crew:
        return Crew(
            agents=[self.social_media_manager()],
            tasks=[self.social_media_task()],
            process=Process.sequential,
            memory=False,
            verbose=True,
        )

    @crew
    def editor_crew(self) -> Crew:
        return Crew(
            agents=[self.editor()],
            tasks=[self.editing_task()],
            process=Process.sequential,
            memory=False,
            verbose=True,
        )

    @crew
    def factcheck_crew(self) -> Crew:
        return Crew(
            agents=[self.fact_checker()],
            tasks=[self.fact_check_task()],
            process=Process.sequential,
            memory=False,
            verbose=True,
        )

    @crew
    def brandcheck_crew(self) -> Crew:
        return Crew(
            agents=[self.brand_guardian()],
            tasks=[self.brandcheck_task()],
            process=Process.sequential,
            memory=False,
            verbose=True,
        )

    @crew
    def topic_crew(self) -> Crew:
        return Crew(
            agents=[self.strategist()],
            tasks=[self.topic_generation_task()],
            process=Process.sequential,
            memory=False,
            verbose=True,
        )

    @crew
    def full_crew(self) -> Crew:
        return Crew(
            agents=[
                self.brand_intel_analyst(),
                self.strategist(),
                self.content_writer(),
                self.editor(),
                self.fact_checker(),
                self.brand_guardian(),
                self.trend_intel_analyst(),
                self.social_media_manager(),
            ],
            tasks=[
                self.brand_intel_refresh_task(),
                self.strategy_outline_task(),
                self.writing_task(),
                self.editing_task(),
                self.fact_check_task(),
                self.brandcheck_task(),
                self.trend_brief_task(),
                self.social_media_task(),
            ],
            process=Process.sequential,
            memory=False,
            verbose=True,
        )
