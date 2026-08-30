from nk_devkb_agent.config import RuntimeConfig, load_env_file


def test_load_env_file_reads_llm_settings(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=openai",
                "LLM_MODEL=gpt-4.1-mini",
                "LLM_API_KEY=sk-test",
                "LLM_BASE_URL=https://example.test/v1",
            ]
        ),
        encoding="utf-8",
    )

    config = RuntimeConfig.from_env_file(env_path)

    assert config.llm_provider == "openai"
    assert config.llm_model == "gpt-4.1-mini"
    assert config.llm_api_key == "sk-test"
    assert config.llm_base_url == "https://example.test/v1"


def test_load_env_file_ignores_comments_and_blank_lines(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("\n# comment\nLLM_PROVIDER=mock\n\n", encoding="utf-8")

    values = load_env_file(env_path)

    assert values == {"LLM_PROVIDER": "mock"}
