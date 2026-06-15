"""
Defines AgentLLMFactory for loading LLM configurations and instantiating
the appropriate ChatCompletion service (Azure, Ollama, OpenAI, or Groq)
based on a JSON configuration file. The MVP uses Groq as the LLM provider.
"""

import json
import os
from openai import AsyncOpenAI
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.services.kernel_services_extension import DEFAULT_SERVICE_NAME
from config import credential_manager
from dotenv import load_dotenv
load_dotenv()

# Use the operating system's native certificate trust store (e.g. the Windows
# cert store). This is required in corporate environments where outbound HTTPS
# is intercepted by a proxy whose root CA is trusted by the OS but not bundled
# in certifi. Safe no-op if truststore is unavailable.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass


class AgentLLMFactory:
    """
    Provides configurations for different LLMs based on a JSON configuration file.
    """

    @staticmethod
    def load_config():
        """
        Loads the JSON configuration file.

        Returns:
            list: A list of LLM configurations.

        Raises:
            FileNotFoundError: If the configuration file is not found.
            json.JSONDecodeError: If the configuration file is not a valid JSON.
        """
        llm_config_file = credential_manager.get_key("LLM_CONFIG_FILE")
        try:
            with open(llm_config_file, "r", encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError as exception:
            raise FileNotFoundError(f"Configuration file '{llm_config_file}' not found.") from exception
        except json.JSONDecodeError as exception:
            raise ValueError(f"Invalid JSON in configuration file: {exception}") from exception

    @staticmethod
    def get_llm_config(agent_llm_model):
        """
            Retrieves the configuration for a specified LLM model.
        """

        config_list = AgentLLMFactory.load_config()

        # Search for the LLM configuration in the JSON
        for agent_llm_config in config_list:
            if agent_llm_model in agent_llm_config:
                agent_llm_model_configuration = agent_llm_config[agent_llm_model]
                # log.debug(f"Configuration for agent '{agent_llm_model}' found in the configuration file.")
                # log.debug(agent_llm_model_configuration)
                agent_llm_model_configuration['api_key'] = credential_manager.get_key \
                    (agent_llm_model_configuration['api_key'])

                return agent_llm_model_configuration

        raise Exception(f"Invalid llm model provided: {agent_llm_model}")

    @staticmethod
    def get_chat_completion(agent_llm_model=None):
        """
            Creates and returns a ChatCompletion service instance based on the LLM configuration.
        """
        if agent_llm_model is None:
            agent_llm_model = credential_manager.get_key("AGENT_LLM_MODEL")

        chat_completion = None
        llm_config = AgentLLMFactory.get_llm_config(agent_llm_model)
        if str(llm_config["api_type"]).lower() == "azure":
            chat_completion = AzureChatCompletion(
                deployment_name=llm_config["model"],
                api_key=llm_config["api_key"],
                endpoint=llm_config["endpoint"],
                service_id=DEFAULT_SERVICE_NAME,  # Optional; for targeting specific services within Semantic Kernel
            )
        elif str(llm_config["api_type"]).lower() == "ollama":
            from semantic_kernel.connectors.ai.ollama import OllamaChatCompletion

            chat_completion = OllamaChatCompletion(
                ai_model_id=llm_config["model"],
                host=llm_config["base_url"],
                service_id=DEFAULT_SERVICE_NAME,  # Optional; for targeting specific services within Semantic Kernel
            )
        elif str(llm_config["api_type"]).lower() == "openai":
            base_url = llm_config.get("base_url")
            if base_url:
                # OpenAI-compatible endpoint (e.g. Gemini's /v1beta/openai/).
                chat_completion = OpenAIChatCompletion(
                    ai_model_id=llm_config["model"],
                    async_client=AsyncOpenAI(
                        api_key=llm_config["api_key"],
                        base_url=base_url,
                    ),
                    service_id=DEFAULT_SERVICE_NAME,
                )
            else:
                chat_completion = OpenAIChatCompletion(
                    ai_model_id=llm_config["model"],
                    api_key=llm_config["api_key"],
                    service_id=DEFAULT_SERVICE_NAME,  # Optional; for targeting specific services within Semantic Kernel
                )
        elif str(llm_config["api_type"]).lower() == "groq":
            chat_completion = OpenAIChatCompletion(
                ai_model_id=llm_config["model"],
                async_client=AsyncOpenAI(
                    api_key=llm_config["api_key"],
                    base_url=llm_config.get("base_url", "https://api.groq.com/openai/v1"),
                ),
                service_id=DEFAULT_SERVICE_NAME,  # Optional; for targeting specific services within Semantic Kernel
            )

        return chat_completion
