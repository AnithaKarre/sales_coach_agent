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
from agent_verse.chat_agent.prompt.prompt_factory import PromptFactory
from utils.logger import log
from config.credential_manager import get_key

AGENT_NAME = "chat_agent"

# Tools this agent is allowed to use (per revised plan §2.3 / §8.3).
# Chat Agent gets: search_data + all 4 merchant tools + update_action + get_audit
# Format: "plugin_name-function_name"
ALLOWED_TOOLS = [
    "merchant_db-search_data",
    "merchant_db-get_merchant_details",
    "merchant_db-get_merchant_score",
    "merchant_db-get_merchant_recommendations",
    "merchant_db-get_merchant_visit_history",
    "merchant_db-update_action",
    "merchant_db-get_audit",
]


class ChatAgent:
    """
    Conversational Q&A agent ("Ask SalesCoach").

    Answers open-ended, grounded questions using:
        - search_data               → broad / comparative merchant queries (pgvector)
        - get_merchant_details      → single-merchant profile
        - get_merchant_score        → single-merchant priority score
        - get_merchant_recommendations → single-merchant recommendations
        - get_merchant_visit_history   → single-merchant visit logs
        - update_action             → mark a recommendation status (DSP / Admin)
        - get_audit                 → query audit logs (Admin only)

    Asks clarifying questions when the query is ambiguous.
    Deflects off-topic questions back to sales coaching context.
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
        log.debug(f"Initializing [🤖] {AGENT_NAME}")

        chat_service = AgentLLMFactory.get_chat_completion()
        kernel.add_service(chat_service)

        # Attach Merchant DB MCP Server via SSE for grounded answers + search
        db_mcp_url = self.plugin_config.get("sse_server_url")
        if not db_mcp_url:
            raise RuntimeError("db_plugin.sse_server_url not configured")

        db_plugin = MCPSsePlugin(name="merchant_db", url=db_mcp_url)
        await db_plugin.connect()
        kernel.add_plugin(db_plugin)

        # Restrict auto tool calling to the Chat Agent's allowed tool set
        settings = kernel.get_prompt_execution_settings_from_service_id(chat_service.service_id)
        settings.function_choice_behavior = FunctionChoiceBehavior.Auto(
            filters={"included_functions": ALLOWED_TOOLS}
        )

        prompt = PromptFactory().get_agent_prompt()

        agent = ChatCompletionAgent(
            kernel=kernel,
            name=AGENT_NAME,
            description="A conversational agent for answering general sales questions with grounded data.",
            instructions=prompt,
            arguments=KernelArguments(settings=settings)
        )
        return agent

    async def run(self):
        chat_agent = await self.get_agent()
        thread: ChatHistoryAgentThread = None
        total_tokens_consumed = 0

        while True:
            user_input = input("Chat with SalesCoach (type 'q' to exit): ")
            if user_input.lower() in ['q', 'quit']:
                print("Exiting...")
                break

            arguments = KernelArguments(now=datetime.now().strftime("%Y-%m-%d %H:%M"))
            result = None
            async for response in chat_agent.invoke(messages=user_input, thread=thread, arguments=arguments):
                result = response
                thread = response.thread

            assistant_response = result.content
            current_token_consumed = self.extract_consumed_token_count(result)
            total_tokens_consumed += current_token_consumed
            
            log.debug("Assistant > " + str(assistant_response))

if __name__ == "__main__":
    asyncio.run(ChatAgent().run())
