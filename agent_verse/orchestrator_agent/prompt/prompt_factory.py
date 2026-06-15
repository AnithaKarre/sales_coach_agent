import os
from docx import Document


class PromptFactory:
    """Factory for loading the Orchestrator Agent prompt."""

    def read_docx_file(self, file_path):
        try:
            doc = Document(file_path)
            paragraphs = [para.text for para in doc.paragraphs]
            return "\n".join(paragraphs)
        except Exception:
            return ""

    def load_prompt_content(self, file_path):
        if not os.path.exists(file_path):
            raise Exception(f"File not found: {file_path}")

        _, extension = os.path.splitext(file_path)
        if extension.lower() == ".txt":
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return ""
        elif extension.lower() == ".docx":
            return self.read_docx_file(file_path)
        else:
            return ""

    def get_agent_prompt(self):
        current_file_directory = os.path.dirname(os.path.abspath(__file__))
        agent_prompt_file = os.path.join(
            current_file_directory, "prompt_library", "SystemBasePrompt.txt"
        )

        if not os.path.exists(agent_prompt_file):
            return (
                "You are the SalesCoach Orchestrator Agent. "
                "Classify intent, validate role, and route to the correct agent."
            )

        return self.load_prompt_content(agent_prompt_file)
