"""
Provides utilities for extracting and logging token usage from Agent response results.
"""

from utils.logger import log


def extract_consumed_token_count(result):
    """
        Extracts token usage counts from a Agent response result.
    """

    if result and hasattr(result, "metadata"):
        usage_info = result.metadata['usage']
        if hasattr(usage_info, "total_tokens"):
            total_tokens = usage_info.total_tokens
            return total_tokens

        if hasattr(usage_info, "prompt_tokens") and hasattr(usage_info, "completion_tokens"):
            total_tokens = usage_info.prompt_tokens + usage_info.completion_tokens
            return usage_info.prompt_tokens, usage_info.completion_tokens, total_tokens

        log.debug("The 'usage' object does not have a 'total_tokens' or 'prompt_tokens' or 'completion_tokens' attribute.")
    else:
        log.debug("The result list is empty or missing the 'usage' attribute.")

    return 0


def log_token_usage(response):
    """
        Logs to stdout the prompt, completion, and total tokens consumed.
    """

    current_prompt_tokens, current_completion_tokens, current_total_token_consumed = extract_consumed_token_count(response)
    print("[💬] > [🪙] Current Prompt Token Consumed : " + str(current_prompt_tokens))
    print("[💬] > [🪙] Current Completion Token Consumed : " + str(current_completion_tokens))
    print("[💬] > [🪙] Current Token Consumed : " + str(current_total_token_consumed))
    return current_prompt_tokens, current_completion_tokens, current_total_token_consumed