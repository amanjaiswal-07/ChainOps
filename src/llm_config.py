import os
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()


def get_llm():
    """
    Get LLM configured for OpenRouter with async support.
    """
    llm = ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        temperature=0.0,
    )
    return llm


def verify_tracing():
    """Verify LangSmith tracing is configured correctly."""
    tracing_enabled = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    api_key = os.getenv("LANGCHAIN_API_KEY")
    project = os.getenv("LANGCHAIN_PROJECT", "default")
    
    if tracing_enabled and api_key:
        print(f"✓ LangSmith tracing enabled")
        print(f"  Project: {project}")
        print(f"  Endpoint: {os.getenv('LANGCHAIN_ENDPOINT', 'https://api.smith.langchain.com')}")
        return True
    else:
        print("⚠ LangSmith tracing disabled")
        return False
