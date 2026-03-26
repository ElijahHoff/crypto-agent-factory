"""FastAPI server: REST API for the agent factory pipeline."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.agents import get_agent, list_agents
from src.models import PipelineStage
from src.utils.registry import ExperimentRegistry

app = FastAPI(
    title="Crypto Agent Factory",
    description="R&D pipeline API for systematic crypto trading strategies",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

registry = ExperimentRegistry()


# ─── Models ──────────────────────────────────────────────────────────────────

class RunPipelineRequest(BaseModel):
    strategy_name: str = "unnamed"


class AgentCallRequest(BaseModel):
    agent_name: str
    context: dict[str, Any] = {}


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "crypto-agent-factory"}


@app.get("/agents")
async def get_agents() -> dict[str, list[str]]:
    """List all available agents."""
    return {"agents": list_agents()}


@app.post("/agents/call")
async def call_agent(req: AgentCallRequest) -> dict[str, Any]:
    """Call a specific agent with context."""
    try:
        agent = get_agent(req.agent_name)
    except KeyError:
        raise HTTPException(404, f"Agent '{req.agent_name}' not found")

    result = agent.run(req.context)
    return {
        "agent": result.agent_name,
        "stage": result.stage,
        "structured": result.structured,
        "warnings": result.warnings,
        "errors": result.errors,
    }


@app.post("/pipeline/run")
async def run_pipeline_endpoint(req: RunPipelineRequest) -> dict[str, Any]:
    """Run the full R&D pipeline (synchronous — can be long-running)."""
    from src.pipeline import run_pipeline

    result = run_pipeline(req.strategy_name)
    return {
        "strategy": req.strategy_name,
        "current_stage": result["current_stage"],
        "decision": result["agent_outputs"].get("decision"),
        "stages_completed": list(result["agent_outputs"].keys()),
    }


@app.get("/experiments")
async def list_experiments(stage: str | None = None) -> dict[str, Any]:
    """List all experiments."""
    stage_enum = PipelineStage(stage) if stage else None
    experiments = registry.list_all(stage=stage_enum)
    return {"experiments": experiments, "total": len(experiments)}


@app.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: str) -> dict[str, Any]:
    """Get a specific experiment."""
    try:
        record = registry.get(experiment_id)
        return record.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(404, f"Experiment '{experiment_id}' not found")


@app.get("/registry/summary")
async def registry_summary() -> dict[str, Any]:
    """Get registry summary."""
    return registry.summary()
