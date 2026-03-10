import os
from dataclasses import dataclass


@dataclass
class Config:
    api_key: str = ""
    model: str = "claude-opus-4-6"
    max_tokens: int = 32000
    max_retries: int = 2
    timeout_seconds: int = 180

    def __post_init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable is not set.\n"
                "Set it with: export ANTHROPIC_API_KEY=your-key-here"
            )
