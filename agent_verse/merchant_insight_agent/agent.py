import asyncio
import sys
from datetime import datetime
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent, ChatHistoryAgentThread
from semantic_kernel.connectors.ai import FunctionChoiceBehavior
from semantic_kernel.connectors.mcp import MCPSsePlugin
from semantic_kernel.functions import KernelArguments
from ai_model.agent_llm_factory import AgentLLMFactory
from agent_verse.merchant_insight_agent.prompt.prompt_factory import PromptFactory
from utils.logger import log
from config.credential_manager import get_key

AGENT_NAME = "merchant_insight_agent"

VALID_MODES = ("profile", "score", "recommendation", "brief")

# This agent exclusively uses Context Injection (RAG) and no longer uses MCP tools.
# See api/routers/merchants.py -> POST /merchants/{id}/generate-brief

class MerchantInsightAgent:
    """
    Consolidated agent that fetches and summarizes merchant data.

    Replaces the former Merchant Profile, Scoring, Recommendation, and Brief
    agents. The desired behavior is selected via the `mode` argument:
    "profile", "score", "recommendation", or "brief" (default).

    Tools (via MCP):
        - get_merchant_details      → profile data
        - get_merchant_score        → daily priority score + signals
        - get_merchant_recommendations → AI-generated actions
        - get_merchant_visit_history   → recent visit logs
    """

    def __init__(self):
        self.plugin_config = self._load_plugin_config()

    def _load_plugin_config(self):
        config_path = get_key("PLUGINS_CONFIG_FILE")
        import json
        with open(config_path, "r") as f:
            data = json.load(f)
            for item in data:
                if "db_plugin" in item:
                    return item["db_plugin"]
        return {}

    def extract_consumed_token_count(self, result):
        if result and hasattr(result, "metadata"):
            usage = result.metadata.get("usage")
            if usage and hasattr(usage, "total_tokens"):
                return usage.total_tokens
        return 0

    async def get_agent(self):
        kernel = Kernel()

        log.debug(f"Initializing [🤖] {AGENT_NAME} (Context Injection Mode)")

        chat_service = AgentLLMFactory.get_chat_completion()
        kernel.add_service(chat_service)

        # Tools and MCP removed: Agent relies 100% on injected SQL context

        prompt = PromptFactory().get_agent_prompt()

        agent = ChatCompletionAgent(
            kernel=kernel,
            name=AGENT_NAME,
            description="Fetches and summarizes merchant profile, score, and recommendations, or compiles a full pre-visit brief.",
            instructions=prompt
        )

        return agent

    async def run(self):
        """
            Runs the merchant insight agent in an interactive loop for testing.
        """
        insight_agent = await self.get_agent()

        thread: ChatHistoryAgentThread = None
        total_tokens_consumed = 0

        while True:
            user_input = input("Enter a merchant name (type 'q' or 'quit' to exit): ")
            if user_input.lower() in ['q', 'quit']:
                print("Exiting...")
                break

            mode = input(f"Mode {VALID_MODES} [brief]: ").strip().lower() or "brief"
            if mode not in VALID_MODES:
                print(f"Invalid mode, defaulting to 'brief'.")
                mode = "brief"

            arguments = KernelArguments(
                now=datetime.now().strftime("%Y-%m-%d %H:%M"),
                mode=mode
            )

            message = f"mode={mode}\nmerchant: {user_input}"

            result = None
            async for response in insight_agent.invoke(messages=message, thread=thread, arguments=arguments):
                result = response
                thread = response.thread

            assistant_response = result.content
            current_token_consumed = self.extract_consumed_token_count(result)
            total_tokens_consumed = total_tokens_consumed + current_token_consumed

            log.debug("Assistant > " + str(assistant_response))
            log.debug("Current Token Consumed : " + str(current_token_consumed))
            log.debug("Total Token Consumed : " + str(total_tokens_consumed))


if __name__ == "__main__":
    asyncio.run(MerchantInsightAgent().run())
