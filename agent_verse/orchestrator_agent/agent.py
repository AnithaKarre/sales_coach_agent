"""
SalesCoach Orchestrator Agent
==============================
Central routing agent that:
  1. Classifies intent (navigation / merchant_insight / chat)
  2. Validates user role (DSP / Manager / Admin)
  3. Routes to the correct sub-agent (Merchant Insight or Chat)
  4. Returns the sub-agent's response

The Orchestrator exposes three SK native functions that the LLM calls
after classifying the user's intent. The sub-agents are injected at
construction time and invoked programmatically.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent, ChatHistoryAgentThread
from semantic_kernel.connectors.ai import FunctionChoiceBehavior
from semantic_kernel.functions import KernelArguments, kernel_function

from ai_model.agent_llm_factory import AgentLLMFactory
from agent_verse.orchestrator_agent.prompt.prompt_factory import PromptFactory
from utils.logger import log

AGENT_NAME = "orchestrator_agent"

VALID_ROLES = ("DSP", "Manager", "Admin")

# Navigation screens the orchestrator can recognize
KNOWN_SCREENS = {
    "dashboard": "dashboard",
    "home": "dashboard",
    "merchant list": "merchant_list",
    "merchants": "merchant_list",
    "settings": "settings",
    "profile": "user_profile",
    "my profile": "user_profile",
    "reports": "reports",
    "analytics": "analytics",
    "audit": "audit_logs",
    "audit logs": "audit_logs",
}


class OrchestratorRouterPlugin:
    """
    Native Semantic Kernel plugin that the Orchestrator Agent's LLM calls
    to route requests. Each function captures the routing intent and stores
    the result so the OrchestratorAgent.invoke() wrapper can read it.
    """

    def __init__(self, insight_agent=None, chat_agent=None):
        self._insight_agent = insight_agent
        self._chat_agent = chat_agent
        self._last_result: Optional[dict] = None

    @property
    def last_result(self) -> Optional[dict]:
        return self._last_result

    def clear(self):
        self._last_result = None

    # ------------------------------------------------------------------
    # Routing functions exposed to the LLM
    # ------------------------------------------------------------------

    @kernel_function(
        name="handle_navigation",
        description=(
            "Call this when the user wants to navigate to a screen in the app. "
            "Pass the target screen or page name (e.g. 'dashboard', 'merchant list', 'settings')."
        ),
    )
    async def handle_navigation(self, screen: str) -> str:
        """Handle a UI navigation request — returns a structured navigation action."""
        normalized = screen.strip().lower()
        resolved = KNOWN_SCREENS.get(normalized, normalized.replace(" ", "_"))

        result = {
            "intent": "navigation",
            "screen": resolved,
            "message": f"Navigating to {resolved.replace('_', ' ').title()}.",
        }
        self._last_result = result
        log.debug(f"[Orchestrator] Navigation → {resolved}")
        return json.dumps(result)

    @kernel_function(
        name="route_to_merchant_insight",
        description=(
            "Call this when the user asks for specific data about a named merchant — "
            "profile, score, recommendation, or a pre-visit brief. "
            "You MUST provide the merchant_name, mode (profile/score/recommendation/brief), "
            "user_id, and user_role."
        ),
    )
    async def route_to_merchant_insight(
        self,
        merchant_name: str,
        mode: str,
        user_id: str,
        user_role: str,
    ) -> str:
        """Route to the Merchant Insight Agent."""
        valid_modes = ("profile", "score", "recommendation", "brief")
        if mode not in valid_modes:
            mode = "brief"

        if user_role not in VALID_ROLES:
            return json.dumps({"intent": "error", "message": "Invalid or missing role. Access denied."})

        message = f"user_id={user_id}\nuser_role={user_role}\nmode={mode}\nmerchant: {merchant_name}"

        log.debug(f"[Orchestrator] Routing to Merchant Insight → merchant={merchant_name}, mode={mode}")

        response_text = ""
        async for response in self._insight_agent.invoke(messages=message):
            response_text = str(response.content)

        result = {
            "intent": "merchant_insight",
            "mode": mode,
            "merchant": merchant_name,
            "answer": response_text,
        }
        self._last_result = result
        return response_text

    @kernel_function(
        name="route_to_chat",
        description=(
            "Call this for open-ended questions, comparative queries, coaching requests, "
            "or any ambiguous question about sales or merchants. "
            "Pass the user's full message, user_id, and user_role."
        ),
    )
    async def route_to_chat(
        self,
        message: str,
        user_id: str,
        user_role: str,
    ) -> str:
        """Route to the Chat Agent."""
        if user_role not in VALID_ROLES:
            return json.dumps({"intent": "error", "message": "Invalid or missing role. Access denied."})

        full_message = f"user_id={user_id}\nuser_role={user_role}\nquestion: {message}"

        log.debug(f"[Orchestrator] Routing to Chat Agent")

        response_text = ""
        async for response in self._chat_agent.invoke(messages=full_message):
            response_text = str(response.content)

        result = {
            "intent": "chat",
            "answer": response_text,
        }
        self._last_result = result
        return response_text


class OrchestratorAgent:
    """
    Top-level orchestrator that builds the SK agent with routing functions.

    Usage:
        orchestrator = OrchestratorAgent()
        agent = await orchestrator.build(insight_agent, chat_agent)
        # Then invoke via the API or interactive loop
    """

    def __init__(self):
        self._router_plugin: Optional[OrchestratorRouterPlugin] = None

    async def build(self, insight_agent, chat_agent):
        """
        Build the orchestrator agent with references to the sub-agents.

        Parameters
        ----------
        insight_agent : ChatCompletionAgent
            The built Merchant Insight Agent (from MerchantInsightAgent().get_agent()).
        chat_agent : ChatCompletionAgent
            The built Chat Agent (from ChatAgent().get_agent()).

        Returns
        -------
        ChatCompletionAgent
            The orchestrator agent ready for invocation.
        """
        kernel = Kernel()
        log.debug(f"Initializing [🤖] {AGENT_NAME}")

        chat_service = AgentLLMFactory.get_chat_completion()
        kernel.add_service(chat_service)

        # Register the router plugin with sub-agent references
        self._router_plugin = OrchestratorRouterPlugin(
            insight_agent=insight_agent,
            chat_agent=chat_agent,
        )
        kernel.add_plugin(self._router_plugin, plugin_name="router")

        # Let the LLM auto-select which routing function to call
        settings = kernel.get_prompt_execution_settings_from_service_id(
            chat_service.service_id
        )
        settings.function_choice_behavior = FunctionChoiceBehavior.Auto()

        prompt = PromptFactory().get_agent_prompt()

        agent = ChatCompletionAgent(
            kernel=kernel,
            name=AGENT_NAME,
            description=(
                "Orchestrator that classifies intent, validates role, "
                "and routes to the correct sub-agent."
            ),
            instructions=prompt,
            arguments=KernelArguments(settings=settings),
        )
        return agent

    @property
    def router_plugin(self) -> Optional[OrchestratorRouterPlugin]:
        return self._router_plugin

    # ------------------------------------------------------------------
    # Interactive loop for local testing
    # ------------------------------------------------------------------
    async def run(self):
        """Interactive CLI loop for testing the orchestrator."""
        from agent_verse.chat_agent.agent import ChatAgent
        from agent_verse.merchant_insight_agent.agent import MerchantInsightAgent

        log.debug("Building sub-agents...")
        insight_agent = await MerchantInsightAgent().get_agent()
        chat_agent_instance = await ChatAgent().get_agent()

        log.debug("Building orchestrator...")
        orchestrator = await self.build(insight_agent, chat_agent_instance)

        thread: ChatHistoryAgentThread = None

        # Default demo user context
        user_id = "294bc771-4a09-4cae-8958-2edc6f4b484d"
        user_role = "DSP"

        print("\n🤖 SalesCoach Orchestrator — type 'q' to exit")
        print(f"   Demo user: {user_id} (role={user_role})\n")

        while True:
            user_input = input("You > ")
            if user_input.strip().lower() in ("q", "quit", "exit"):
                print("Goodbye!")
                break

            message = f"user_id={user_id}\nuser_role={user_role}\n{user_input}"

            result = None
            async for response in orchestrator.invoke(
                messages=message, thread=thread
            ):
                result = response
                thread = response.thread

            if result:
                print(f"\nAssistant > {result.content}\n")


if __name__ == "__main__":
    asyncio.run(OrchestratorAgent().run())
