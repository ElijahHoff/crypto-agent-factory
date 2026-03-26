"""Agent registry: central lookup for all factory agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agents.auditor import Auditor
from src.agents.backtesting_engineer import BacktestingEngineer
from src.agents.data_engineer import DataEngineer
from src.agents.feature_engineer import FeatureEngineer
from src.agents.market_analyst import MarketAnalyst
from src.agents.paper_trading import PaperTrading
from src.agents.portfolio_construction import PortfolioConstruction
from src.agents.quant_formalization import QuantFormalization
from src.agents.research_director import ResearchDirector
from src.agents.risk_manager import RiskManager
from src.agents.statistician import Statistician
from src.agents.strategy_ideation import StrategyIdeation

if TYPE_CHECKING:
    from src.agents.base import BaseAgent

AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "research_director": ResearchDirector,
    "market_analyst": MarketAnalyst,
    "strategy_ideation": StrategyIdeation,
    "quant_formalization": QuantFormalization,
    "data_engineer": DataEngineer,
    "feature_engineer": FeatureEngineer,
    "backtesting_engineer": BacktestingEngineer,
    "risk_manager": RiskManager,
    "statistician": Statistician,
    "portfolio_construction": PortfolioConstruction,
    "paper_trading": PaperTrading,
    "auditor": Auditor,
}


_instances: dict[str, BaseAgent] = {}


def get_agent(name: str) -> BaseAgent:
    """Get or create a singleton agent instance."""
    if name not in _instances:
        if name not in AGENT_CLASSES:
            raise KeyError(f"Unknown agent: {name}. Available: {list(AGENT_CLASSES)}")
        _instances[name] = AGENT_CLASSES[name]()
    return _instances[name]


def list_agents() -> list[str]:
    return list(AGENT_CLASSES.keys())
